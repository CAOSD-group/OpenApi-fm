import json
import yaml
import os
from pathlib import Path
from copy import deepcopy
from flamapy.metamodels.configuration_metamodel.models.configuration import Configuration

def sanitize(name):
    """Limpia los caracteres especiales para igualar el formato del generador UVL"""
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

class ConfigurationOpenAPI:
    def __init__(self, path: str) -> None:
        p = Path(path)
        if not p.is_absolute():
            base = Path(__file__).resolve().parent
            p = (base / p).resolve()
        self._path = str(p)
        
        # Mapeo de diccionarios de OpenAPI a los Wrappers inyectados por el UVL.
        # Ajusta esto si detectas que otros mapas (ej. schemas, security) generan un wrapper.
        self.MAP_WRAPPERS = {
            "paths": "PathItem",
            "headers": "Value",
            "properties": "Value",
            "mapping": "Value"
        }

    def read_file(self) -> dict:
        p = Path(self._path)
        if not p.exists():
            raise FileNotFoundError(f"No se encontró el archivo: {p}")

        with p.open('r', encoding='utf-8') as f:
            if p.suffix.lower() in ['.yaml', '.yml']:
                return yaml.safe_load(f)
            else:
                return json.load(f)

    def transform(self):
        """
        Transforma el documento OpenAPI (YAML/JSON) en una configuración Flamapy.
        """
        raw_data = self.read_file()
        
        # Iniciar la configuración base activando la raíz abstracta
        base_config = {"OpenAPI_Document": True}

        # Extraer características recursivamente
        self.extract_features(raw_data, base_config, parent_path=[])

        # Por ahora, devolvemos una única configuración lineal para validar el mapeo
        return [Configuration(base_config)]

    def extract_features(self, data, config, parent_path):
        """
        Recorre el documento OpenAPI y aplana la jerarquía uniendo los nombres con '_',
        respetando las inyecciones de KeyValue y Wrappers del modelo UVL.
        """
        if isinstance(data, dict):
            for k, v in data.items():
                current_parent = "_".join(parent_path) if parent_path else ""
                sanitized_k = sanitize(k)
                last_node = parent_path[-1] if parent_path else ""

                # CASO 1: Estamos dentro de un diccionario dinámico (ej. paths, headers)
                if last_node in self.MAP_WRAPPERS:
                    wrapper_name = self.MAP_WRAPPERS[last_node]
                    
                    # Activar el wrapper (ej. paths_PathItem)
                    wrapper_full_name = f"{current_parent}_{wrapper_name}" if current_parent else wrapper_name
                    config[wrapper_full_name] = True
                    
                    # Asignar la clave original al KeyValue (ej. paths_PathItem_KeyValue = "/pet")
                    kv_name = f"{wrapper_full_name}_KeyValue"
                    config[kv_name] = str(k)
                    
                    # Procesar el contenido colgándolo del wrapper
                    self.extract_features(v, config, parent_path + [wrapper_name])
                
                # CASO 2: Procesamiento normal de propiedades
                else:
                    feat_name = f"{current_parent}_{sanitized_k}" if current_parent else sanitized_k
                    
                    # Si la clave original era algo como '200' en responses, el generador a veces
                    # anida directamente una referencia (ej. _Response). Lo procesamos normal.
                    
                    if isinstance(v, (str, int, float, bool)):
                        config[feat_name] = v
                        
                    elif isinstance(v, dict):
                        config[feat_name] = True
                        self.extract_features(v, config, parent_path + [sanitized_k])
                        
                    elif isinstance(v, list):
                        config[feat_name] = True
                        # Simplificación para arrays (tags, servers): procesar solo el primero para testing
                        if len(v) > 0:
                            # Dependiendo del UVL, los arrays a veces inyectan wrappers. 
                            # Si es un array puro, le pasamos el nombre actual como padre.
                            self.extract_features(v[0], config, parent_path + [sanitized_k])

        elif isinstance(data, list):
            # Fallback en caso de que la raíz o un nodo suelto sea una lista pura
            if len(data) > 0:
                 self.extract_features(data[0], config, parent_path)

if __name__ == '__main__':
    # Sustituye por la ruta a tu archivo petstore.yaml o petstore.json
    path_file = '../resources/petstore.yaml'

    configuration_reader = ConfigurationOpenAPI(path_file)
    configurations = configuration_reader.transform()

    print(f"✅ Configuraciones generadas: {len(configurations)}")
    for i, config in enumerate(configurations):
        print(f'\n--- Configuration {i+1} ---')
        # Imprimir de forma ordenada para verificar visualmente
        for k, v in sorted(config.elements.items()):
            print(f"{k}: {v}")