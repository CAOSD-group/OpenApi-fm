import json
import yaml
from pathlib import Path
from flamapy.metamodels.configuration_metamodel.models.configuration import Configuration

def sanitize(name):
    """Limpia los caracteres especiales para igualar el formato del generador UVL"""
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

class SimpleAutomatedOpenAPIReader:
    def __init__(self, yaml_path, rules_path="openapi_extraction_rules.json"):
        # 1. Cargar las reglas generadas por el Metaesquema
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)
            
        # 2. Cargar el YAML de instancia (ej. petstore.yaml)
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.yaml_data = yaml.safe_load(f)

    def transform(self):
        """Genera una configuración plana para Flamapy"""
        config_flat = {"OpenAPI_Document": True}
        self._map_recursive(self.yaml_data, config_flat, path=[])
        return [Configuration(config_flat)]
    
    def _determine_polymorph(self, v, options):
        """Heurística inteligente para resolver polimorfismo anidado y discriminadores"""
        if isinstance(v, dict) and "$ref" in v:
            return "Reference"
            
        real_opts = [o for o in options if o != "Reference"]
        if not real_opts:
            return options[0]
        if len(real_opts) == 1:
            return real_opts[0]
            
        if isinstance(v, dict):
            # 1. Discriminador genérico 'type' (ej. type: oauth2 -> OAuth2SecurityScheme)
            if "type" in v:
                t_val = str(v["type"]).lower().replace("_", "")
                for opt in real_opts:
                    if t_val in opt.lower(): return opt
                    
            # 2. Discriminador 'in' para Parámetros (ej. in: header -> HeaderParameter)
            if "in" in v:
                in_val = str(v["in"]).lower()
                for opt in real_opts:
                    if in_val in opt.lower(): return opt
                    
            # 3. Discriminador especial para HTTPSecurityScheme (Bearer vs Non_Bearer)
            if "scheme" in v:
                if str(v["scheme"]).lower() == "bearer": return "Bearer"
                else: return "Non_Bearer"
                
        # Si no hay discriminador claro, elegimos la primera opción real
        return real_opts[0]
    
    def _map_recursive(self, data, config, path):
        if isinstance(data, dict):
            for k, v in data.items():

                if str(k).startswith("x-"):
                    continue # Ignorar extensiones personalizadas de OpenAPI (x-*)

                # Reconstruir la ruta jerárquica
                current_parent = "_".join(path) if path else ""
                sanitized_k = sanitize(k)
                feat_name = f"{current_parent}_{sanitized_k}" if current_parent else sanitized_k
                
                # --- CASO 1: MAPAS DINÁMICOS (ej. paths, responses, properties) ---
                if k in self.rules.get("map_wrappers", {}):
                    wrapper = self.rules["map_wrappers"][k]
                    wrapper_feat = f"{feat_name}_{wrapper}"
                    config[wrapper_feat] = True
                    
                    # VERSIÓN SIMPLE: Cogemos solo la primera clave del diccionario
                    if isinstance(v, dict) and v:
                        first_key = list(v.keys())[0]
                        first_val = v[first_key]
                        config[f"{wrapper_feat}_KeyValue"] = str(first_key)
                        
                        # NUEVO: Verificar si el envoltorio del mapa es polimórfico (ej. ResponseValue)
                        if wrapper in self.rules.get("polymorphic_keys", {}):
                            opts = self.rules["polymorphic_keys"][wrapper]
                            # Decidimos si es Reference o el tipo nativo
                            #actual_wrapper = "Reference" if isinstance(first_val, dict) and "$ref" in first_val else opts[0]
                            actual_wrapper = "Reference" if isinstance(first_val, dict) and "$ref" in first_val else next((opt for opt in opts if opt != "Reference"), opts[0])
                            poly_feat = f"{wrapper_feat}_{actual_wrapper}"
                            config[poly_feat] = True
                            
                            self._map_recursive(first_val, config, path + [sanitized_k, wrapper, actual_wrapper])
                        else:
                            # Mapas no polimórficos
                            self._map_recursive(first_val, config, path + [sanitized_k, wrapper])
                
                # --- CASO 2: CLAVES POLIMÓRFICAS (ej. schema, requestBody) ---
                elif k in self.rules.get("polymorphic_keys", {}):
                    config[feat_name] = True
                    options = self.rules["polymorphic_keys"][k]
                    
                    # Decidimos dinámicamente si es una Referencia o el tipo nativo
                    #selected = "Reference" if isinstance(v, dict) and "$ref" in v else options[0]
                    selected = "Reference" if isinstance(v, dict) and "$ref" in v else next((opt for opt in options if opt != "Reference"), options[0])
                    poly_feat = f"{feat_name}_{selected}"
                    config[poly_feat] = True
                    
                    self._map_recursive(v, config, path + [sanitized_k, selected])

                # --- CASO 3: PROCESAMIENTO NORMAL Y ARRAYS ---
                else:
                    if isinstance(v, (str, int, float, bool)):
                        # Casuística de booleanos permitidos como schemas
                        if k == "additionalProperties" and isinstance(v, bool):
                            config[f"{feat_name}_Boolean"] = v
                        else:
                            config[feat_name] = v
                            
                    elif isinstance(v, dict):
                        config[feat_name] = True
                        self._map_recursive(v, config, path + [sanitized_k])
                        
                    elif isinstance(v, list):
                        config[feat_name] = True
                        
                        # VERSIÓN SIMPLE: Procesamos solo el primer elemento del array [0]
                        if len(v) > 0:
                            item = v[0]
                            if isinstance(item, dict):
                                # Determinamos polimorfismo si el item es una referencia (ej. schemas)
                                if k in self.rules.get("polymorphic_keys", {}):
                                    opts = self.rules["polymorphic_keys"][k]
                                    actual_wrapper = "Reference" if "$ref" in item else opts[0]
                                    wrapper_full_name = f"{feat_name}_{actual_wrapper}"
                                    config[wrapper_full_name] = True
                                    
                                    self._map_recursive(item, config, path + [sanitized_k, actual_wrapper])
                                else:
                                    # ✅ ENFOQUE APLANADO DEFINITIVO
                                    # Para "servers", "tags", etc. Pasa directamente a las propiedades.
                                    self._map_recursive(item, config, path + [sanitized_k])
                            else:
                                # Arrays de strings/enteros simples (ej. enum, required)
                                item_wrapper = self.rules.get("array_items", {}).get(k)
                                val_feat_name = f"{feat_name}_{item_wrapper}" if item_wrapper else f"{feat_name}_StringValue"
                                config[val_feat_name] = item

        # Backup por si el documento entero es una lista
        elif isinstance(data, list):
            if len(data) > 0:
                self._map_recursive(data[0], config, path)