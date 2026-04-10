import yaml
import json
import re
import os

def sanitize(name):
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

class OpenAPI_Structured_Mapper:
    def __init__(self, yaml_path):
        with open(yaml_path, 'r', encoding='utf-8') as f:
            self.api_spec = yaml.safe_load(f)

    def generate_config(self, output_json_path):
        print("Mapeando YAML a configuración jerárquica UVL...")
        
        # La raíz del documento
        config_tree = {
            "OpenAPI_Document": True,
            **self._traverse_dict(self.api_spec, parent_name="")
        }
        
        # Guardar la configuración extraída
        os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(config_tree, f, indent=4, ensure_ascii=False)
            
        print(f"Configuración jerárquica guardada en: {output_json_path}")

    def _traverse_dict(self, data_dict, parent_name):
        """Recorre recursivamente un diccionario manteniendo la estructura jerárquica."""
        result = {}
        for key, value in data_dict.items():
            if str(key).startswith("x-"): continue  # Ignorar vendor extensions
            
            safe_key = sanitize(key)
            feat_name = f"{parent_name}_{safe_key}" if parent_name else safe_key

            # --- MAPAS DINÁMICOS CONOCIDOS ---
            # Identificamos los patternProperties que en UVL transformamos en [0..*]
            if parent_name == "" and key == "paths":
                result[feat_name] = self._handle_map(value, feat_name, "PathItem")
                
            elif parent_name == "components" and key in ["schemas", "responses", "parameters", "examples", "requestBodies", "headers", "securitySchemes", "links", "callbacks"]:
                # Generar el nombre en singular basándonos en la clave (ej: schemas -> Schema)
                if key == "schemas": item_suffix = "Schema"
                elif key == "securitySchemes": item_suffix = "SecurityScheme"
                elif key == "requestBodies": item_suffix = "RequestBody"
                else: item_suffix = key[:-1].capitalize() if key.endswith('s') else key.capitalize()
                
                result[feat_name] = self._handle_map(value, feat_name, item_suffix)
                
            # --- CASO SECURITY (Array de Mapas) ---
            elif parent_name == "" and key == "security":
                result[feat_name] = self._handle_security_array(value, feat_name)

            # --- PROPIEDADES NORMALES ---
            else:
                if isinstance(value, dict):
                    result[feat_name] = self._traverse_dict(value, feat_name)
                elif isinstance(value, list):
                    result[feat_name] = self._traverse_list(value, feat_name, key)
                else:
                    result[feat_name] = value # Valores primitivos (Strings, Bools, Ints)
                    
        return result

    def _handle_map(self, map_dict, parent_feat, item_suffix):
        """Convierte un diccionario YAML en una lista de instanciaciones con KeyValue para el UVL."""
        if not isinstance(map_dict, dict): return {}
        
        instances = []
        item_feat_name = f"{parent_feat}_{item_suffix}"
        
        for k, v in map_dict.items():
            if str(k).startswith("x-"): continue
            
            # Instanciamos el elemento del mapa con su Key obligatoria
            instance = {
                f"{item_feat_name}_KeyValue": k
            }
            
            # Colgamos las propiedades internas del valor
            if isinstance(v, dict):
                instance.update(self._traverse_dict(v, item_feat_name))
                
            instances.append(instance)
            
        # Devolvemos el nodo clonable apuntando a la lista de instancias
        return { item_feat_name: instances }

    def _traverse_list(self, data_list, parent_feat, original_key):
        """Convierte una lista YAML en una lista de configuraciones estructuradas."""
        instances = []
        
        # Deducción heurística del nombre del elemento del array (ej: servers -> Server)
        item_suffix = "Item"
        if original_key == "servers": item_suffix = "Server"
        elif original_key == "tags": item_suffix = "Tag"
        elif original_key == "parameters": item_suffix = "Parameter"
        
        for item in data_list:
            if isinstance(item, dict):
                # Array de objetos
                child_name = f"{parent_feat}_{item_suffix}"
                instance_dict = self._traverse_dict(item, child_name)
                # Opcional: inyectar el nombre del nodo padre si es necesario para tu configurador
                instances.append({child_name: instance_dict} if instance_dict else {child_name: True})
            else:
                # Array de primitivos
                t_name = type(item).__name__.capitalize()
                if t_name == "Str": t_name = "String"
                if t_name == "Int": t_name = "Integer"
                if t_name == "Float": t_name = "Number"
                child_name = f"{parent_feat}_{t_name}Value"
                
                instances.append({child_name: item})
                
        return instances

    def _handle_security_array(self, security_list, feat_name):
        """Caso súper específico de OpenAPI: security es un array de mapas donde los valores son arrays."""
        instances = []
        map_entry_name = f"{feat_name}_MapEntry"
        
        for sec_req in security_list: # sec_req es un dict
            for k, v in sec_req.items():
                sec_instance = {
                    f"{map_entry_name}_KeyValue": k
                }
                # El valor es un array de scopes (strings)
                if isinstance(v, list):
                    arr_name = f"{map_entry_name}_Array"
                    sec_instance[arr_name] = self._traverse_list(v, arr_name, "")
                    
                instances.append({map_entry_name: sec_instance})
                
        return instances

if __name__ == "__main__":
    parser = OpenAPI_Structured_Mapper("../resources/petstore.yaml")
    parser.generate_config("../resources/petstore_config.json")
    print("Mapper jerárquico listo.")