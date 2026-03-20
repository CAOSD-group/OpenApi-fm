import yaml
import jsonref
import os

def sanitize(name):
    return name.replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "")

def clean_description(description: str) -> str:
    if not description: return ""
    return description.replace('\n', ' ').replace('`', '').replace("'", "_").replace('"', '').replace("\\", "_")

class OpenAPI_Integral_Parser:
    def __init__(self, openapi_path):
        # 1. Cargar el OpenAPI y resolver TODOS los $ref automáticamente
        with open(openapi_path, 'r', encoding='utf-8') as f:
            self.openapi = jsonref.loads(yaml.safe_load(f))
        self.uvl_lines = []
    
    def generate_uvl(self, output_path):
        # 2. Raíz del sistema
        api_title = sanitize(self.openapi.get("info", {}).get("title", "OpenAPI_System"))
        self.uvl_lines = [f"namespace {api_title}", "features", f"\t{api_title} {{abstract}}", "\t\tmandatory"]

        # 3. Extraer la información de la API
        self._parse_info()
        
        # 4. Extraer los Paths (El núcleo del Enfoque Integral)
        self._parse_paths()

        # Guardar archivo
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.uvl_lines))
        print(f"UVL Integral generado: {output_path}")

    def _parse_info(self):
        info = self.openapi.get("info", {})
        self.uvl_lines.append("\t\t\tInfo")
        self.uvl_lines.append("\t\t\t\tmandatory")
        version = info.get('version', 'unknown')
        self.uvl_lines.append(f"\t\t\t\t\tString api_version {{default '{version}'}}")

    def _parse_paths(self):
        paths = self.openapi.get("paths", {})
        if not paths: return

        self.uvl_lines.append("\t\t\tPaths")
        self.uvl_lines.append("\t\t\t\toptional") # Las rutas suelen ser opcionales en el modelado de variabilidad
        
        for path_name, path_item in paths.items():
            safe_path_name = sanitize(path_name)
            self.uvl_lines.append(f"\t\t\t\t\tEndpoint_{safe_path_name}")
            self.uvl_lines.append(f"\t\t\t\t\t\toptional")

            # Iterar sobre los métodos HTTP (get, post, put, delete...)
            for method, operation in path_item.items():
                if method.lower() not in ['get', 'post', 'put', 'delete', 'patch']: continue
                
                method_name = f"Method_{method.upper()}"
                doc = clean_description(operation.get("summary", "") or operation.get("description", ""))
                self.uvl_lines.append(f"\t\t\t\t\t\t\t{method_name} {{doc '{doc}'}}")
                
                # Expandir RequestBody y Parameters dentro del método
                self._parse_operation_details(operation, indent=8)

    def _parse_operation_details(self, operation, indent):
        i = "\t" * indent
        has_params = "parameters" in operation
        has_body = "requestBody" in operation

        if has_params or has_body:
            self.uvl_lines.append(f"{i}optional")
            
            # Procesar RequestBody (Aquí es donde ocurre la expansión de los Schemas)
            if has_body:
                content = operation.get("requestBody", {}).get("content", {})
                # Generalmente se asume application/json
                schema = content.get("application/json", {}).get("schema", {})
                if schema:
                    self.uvl_lines.append(f"{i}\tRequestBody")
                    # ¡Llamamos a tu función lógica de extracción de características!
                    features = self.extract_features(schema, parent_name="Body")
                    self._render_features_to_lines(features, indent + 2)

            # Procesar Parameters (Query, Header, Path)
            if has_params:
                self.uvl_lines.append(f"{i}\tParameters")
                for param in operation["parameters"]:
                    param_name = sanitize(param.get("name", "param"))
                    param_in = param.get("in", "query")
                    param_schema = param.get("schema", {})
                    req = "mandatory" if param.get("required") else "optional"
                    
                    self.uvl_lines.append(f"{i}\t\t{req}")
                    self.uvl_lines.append(f"{i}\t\t\t{param_in}_{param_name}")
                    
                    # Expandir el esquema del parámetro
                    if param_schema:
                        features = self.extract_features(param_schema, parent_name="")
                        self._render_features_to_lines(features, indent + 4)

    def extract_features(self, schema, parent_name="", required_fields=None, depth=0):
        # Para evitar bucles infinitos generados por jsonref en esquemas cíclicos
        if depth > 10: return [] 
        return []

    def _render_features_to_lines(self, features, indent):
        pass

# Uso de prueba
# parser = OpenAPI_Integral_Parser("petstore.yaml")
# parser.generate_uvl("petstore_integral.uvl")