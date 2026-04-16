import json
import yaml
from pathlib import Path
from flamapy.metamodels.configuration_metamodel.models.configuration import Configuration

def sanitize(name):
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

class AutomatedOpenAPIReader:
    def __init__(self, yaml_path, rules_path="openapi_extraction_rules.json"):
        # Cargar las reglas generadas automáticamente
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)
            
        # Cargar el YAML instanciado
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.yaml_data = yaml.safe_load(f)

    def transform(self):
        config_flat = {"OpenAPI_Document": True}
        self._map_recursive(self.yaml_data, config_flat, path=[])
        return [Configuration(config_flat)]

    def _map_recursive(self, data, config, path):
        if isinstance(data, dict):
            for k, v in data.items():
                # Nombre del padre hasta ahora
                current_parent = "_".join(path) if path else ""
                sanitized_k = sanitize(k)
                feat_name = f"{current_parent}_{sanitized_k}" if current_parent else sanitized_k
                
                # 1. MAPAS DINÁMICOS (ej. paths -> /pet)
                if k in self.rules.get("map_wrappers", {}):
                    wrapper = self.rules["map_wrappers"][k]
                    wrapper_feat = f"{feat_name}_{wrapper}"
                    config[wrapper_feat] = True
                    
                    if isinstance(v, dict):
                        for sub_k, sub_v in v.items():
                            config[f"{wrapper_feat}_KeyValue"] = str(sub_k)
                            # Continuamos la recursión saltándonos la clave dinámica para mantener la ruta limpia
                            self._map_recursive(sub_v, config, path + [sanitized_k, wrapper])
                
                # 2. CLAVES POLIMÓRFICAS (ej. requestBody)
                elif k in self.rules.get("polymorphic_keys", {}):
                    config[feat_name] = True
                    options = self.rules["polymorphic_keys"][k]
                    
                    # Heurística dinámica básica basada en el $ref
                    selected = "Reference" if isinstance(v, dict) and "$ref" in v else options[0]
                    poly_feat = f"{feat_name}_{selected}"
                    config[poly_feat] = True
                    
                    self._map_recursive(v, config, path + [sanitized_k, selected])

                # 3. PROCESAMIENTO NORMAL (Objetos, Primitivos o Arrays)
                else:
                    if isinstance(v, (str, int, float, bool)):
                        if k == "additionalProperties" and isinstance(v, bool):
                            config[f"{feat_name}_Boolean"] = v
                        else:
                            config[feat_name] = v
                            
                    elif isinstance(v, dict):
                        config[feat_name] = True
                        self._map_recursive(v, config, path + [sanitized_k])
                        
                    elif isinstance(v, list):
                        config[feat_name] = True
                        
                        # VERIFICAR SI EL ARRAY TIENE UN ENVOLTORIO EN LAS REGLAS (ej. tags -> Tag)
                        item_wrapper = self.rules.get("array_items", {}).get(k)
                        
                        # PROCESAR TODOS LOS ELEMENTOS DEL ARRAY INDEXADOS (_1, _2...)
                        for index, item in enumerate(v, start=1):
                            indexed_node_name = f"{sanitized_k}_{index}"
                            
                            if isinstance(item, dict):
                                if item_wrapper:
                                    # Determinar polimorfismo en los items del array (ej. Parameter vs Reference)
                                    if k in self.rules.get("polymorphic_keys", {}):
                                        opts = self.rules["polymorphic_keys"][k]
                                        actual_wrapper = "Reference" if "$ref" in item else opts[0]
                                    else:
                                        actual_wrapper = item_wrapper
                                        
                                    wrapper_full_name = f"{current_parent}_{indexed_node_name}_{actual_wrapper}" if current_parent else f"{indexed_node_name}_{actual_wrapper}"
                                    config[wrapper_full_name] = True
                                    self._map_recursive(item, config, path + [indexed_node_name, actual_wrapper])
                                else:
                                    self._map_recursive(item, config, path + [indexed_node_name])
                            else:
                                # Array de primitivos (ej. [ "read:pets", "write:pets" ])
                                val_feat_name = f"{current_parent}_{indexed_node_name}_StringValue" if current_parent else f"{indexed_node_name}_StringValue"
                                config[val_feat_name] = item

        elif isinstance(data, list):
            for index, item in enumerate(data, start=1):
                self._map_recursive(item, config, path + [f"Item_{index}"])

if __name__ == "__main__":
    reader = AutomatedOpenAPIReader("../resources/openapi/petstore.yaml")
    configs = reader.transform()
    
    print("✅ Mapeo completado. Variables extraídas:")
    # Imprimimos las primeras 30 variables para comprobar
    for k, v in list(configs[0].elements.items())[:30]:
        print(f"{k}: {v}")