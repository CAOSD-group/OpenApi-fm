import json
import yaml
from pathlib import Path
from flamapy.metamodels.configuration_metamodel.models.configuration import Configuration

def sanitize(name):
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

class SimpleAutomatedOpenAPIReader:
    def __init__(self, yaml_path, rules_path="openapi_extraction_rules.json"):
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = json.load(f)
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.yaml_data = yaml.safe_load(f)

    def transform(self):
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
                if str(k).startswith("x-"): continue
                
                current_parent = "_".join(path) if path else ""
                sanitized_k = sanitize(k)
                feat_name = f"{current_parent}_{sanitized_k}" if current_parent else sanitized_k
                
                # --- CASO 1: MAPAS DINÁMICOS ---
                if k in self.rules.get("map_wrappers", {}):
                    wrapper = self.rules["map_wrappers"][k]
                    wrapper_feat = f"{feat_name}_{wrapper}"
                    config[wrapper_feat] = True
                    
                    if isinstance(v, dict) and v:
                        first_key = list(v.keys())[0]
                        first_val = v[first_key]
                        config[f"{wrapper_feat}_KeyValue"] = str(first_key)
                        
                        # RESOLUCIÓN DE POLIMORFISMO ANIDADO (Bucle While)
                        current_wrapper = wrapper
                        poly_path = []
                        
                        while current_wrapper in self.rules.get("polymorphic_keys", {}):
                            opts = self.rules["polymorphic_keys"][current_wrapper]
                            selected = self._determine_polymorph(first_val, opts)
                            poly_path.append(selected)
                            current_wrapper = selected
                            
                        current_feat = wrapper_feat
                        for p in poly_path:
                            current_feat = f"{current_feat}_{p}"
                            config[current_feat] = True
                            
                        if poly_path:
                            self._map_recursive(first_val, config, path + [sanitized_k, wrapper] + poly_path)
                        else:
                            self._map_recursive(first_val, config, path + [sanitized_k, wrapper])
                            
                # --- CASO 2: CLAVES POLIMÓRFICAS ---
                elif k in self.rules.get("polymorphic_keys", {}):
                    config[feat_name] = True
                    
                    current_k = k
                    poly_path = []
                    
                    # Bucle para polimorfismo anidado
                    while current_k in self.rules.get("polymorphic_keys", {}):
                        opts = self.rules["polymorphic_keys"][current_k]
                        selected = self._determine_polymorph(v, opts)
                        poly_path.append(selected)
                        current_k = selected
                        
                    current_feat = feat_name
                    for p in poly_path:
                        current_feat = f"{current_feat}_{p}"
                        config[current_feat] = True
                        
                    self._map_recursive(v, config, path + [sanitized_k] + poly_path)

                # --- CASO 3: NORMAL Y ARRAYS ---
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
                        if len(v) > 0:
                            item = v[0]
                            if isinstance(item, dict):
                                if k in self.rules.get("polymorphic_keys", {}):
                                    current_k = k
                                    poly_path = []
                                    while current_k in self.rules.get("polymorphic_keys", {}):
                                        opts = self.rules["polymorphic_keys"][current_k]
                                        selected = self._determine_polymorph(item, opts)
                                        poly_path.append(selected)
                                        current_k = selected
                                        
                                    current_feat = feat_name
                                    for p in poly_path:
                                        current_feat = f"{current_feat}_{p}"
                                        config[current_feat] = True
                                        
                                    self._map_recursive(item, config, path + [sanitized_k] + poly_path)
                                else:
                                    self._map_recursive(item, config, path + [sanitized_k])
                            else:
                                item_wrapper = self.rules.get("array_items", {}).get(k)
                                val_feat_name = f"{feat_name}_{item_wrapper}" if item_wrapper else f"{feat_name}_StringValue"
                                config[val_feat_name] = item

        elif isinstance(data, list):
            if len(data) > 0:
                self._map_recursive(data[0], config, path)