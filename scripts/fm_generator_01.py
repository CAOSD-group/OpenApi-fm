import json
import os

def sanitize(name):
    """Limpia los nombres eliminando caracteres especiales de OpenAPI"""
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

def clean_description(description: str) -> str:
    if not description: return ""
    return description.replace('\n', ' ').replace('`', '').replace('´', '').replace("'", "_").replace('{', '').replace('}', '').replace('"', '').replace("\\", "_")

def render_feature(entry, indent=2):
    """Renderiza el nodo a formato UVL evaluando su obligatoriedad y cardinalidad"""
    i = "\t" * indent
    lines = []

    typename = "" if entry.get("type") in ["object", "array", ""] else entry.get("type", "").capitalize()
    name = sanitize(entry["name"])
    doc = entry.get("description", "")
    default = entry.get("default")
    enum = entry.get("enum", [])
    children = entry.get("children", [])

    attributes = []
    if default is not None:
        val = str(default).lower() if isinstance(default, bool) else f"'{default}'"
        attributes.append(f'default {val}')

    if doc:
        attributes.append(f"doc '{clean_description(doc.strip())}'")

    attr_str = f" {{{', '.join(attributes)}}}" if attributes else ""
    
    # Aplicar cardinalidad
    if entry.get("cardinality"):
        lines.append(f"{i}{name} cardinality {entry['cardinality']}{attr_str}")
    else:
        # Tipos primitivos
        if typename and typename != 'Boolean' and not enum:
            lines.append(f"{i}{typename} {name}{attr_str}")
        else:
            lines.append(f"{i}{name}{attr_str}")
            
    # Valores de Enum
    if enum and len(enum) > 1:
        
        lines.append(i + "\talternative")
        for val in enum:
            enum_val = sanitize(f"{name}_{val}")
            lines.append(f"{i}\t\t{enum_val} {{doc 'Specific value: {sanitize(str(val))}'}}")
    elif enum and len(enum) == 1:
        # Si solo hay un valor en el enum, lo tratamos como un default implícito
        print(f"Enumeration detected for {name}: {enum}")
        val = enum[0]
        lines.append(i + "\toptional")
        #val_str = str(val).lower() if isinstance(val, bool) else f"'{val}'"
        enum_val = sanitize(f"{name}_{val}")
        lines.append(f"{i}\t\t{enum_val} {{doc 'Specific value: {sanitize(str(val))}'}}")
    
        #lines[-1] += f" {{default {val_str}}}"

    # Renderizar hijos
    if children: ## No hay children en el JSON
        # Separar por tipos lógicos
        mand = [c for c in children if c.get("required") and not c.get("is_alternative")]
        opt = [c for c in children if not c.get("required") and not c.get("is_alternative")]
        alt = [c for c in children if c.get("is_alternative")]
        
        if mand:
            lines.append(i + "\tmandatory")
            for c in mand:
                lines.extend(render_feature(c, indent + 2))
        if opt:
            lines.append(i + "\toptional")
            for c in opt:
                lines.extend(render_feature(c, indent + 2))
        if alt:
            lines.append(i + "\talternative")
            for c in alt:
                lines.extend(render_feature(c, indent + 2))

    return lines


class MetaSchema_UVL_Parser:
    def __init__(self, json_path):
        print(f"Cargando JSON Schema: {json_path}...")
        with open(json_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)
        self.uvl_lines = []

    def resolve_reference(self, ref):
        """Resuelve el $ref manualmente navegando por el JSON cargado en memoria"""
        parts = ref.strip('#/').split('/')
        schema_node = self.schema
        try:
            for part in parts:
                schema_node = schema_node.get(part, {})
                if not schema_node:
                    return None
            return schema_node
        except Exception as e:
            return None

    def generate_uvl(self, output_path):
        self.uvl_lines = [
            "namespace OpenAPI_3_0_Specification", 
            "features", 
            "\tOpenAPI_Document {abstract, doc 'Root of an OpenAPI v3.0.x Document'}", 
            "\t\tmandatory"
        ]

        # Inicia recursividad desde la raíz del JSON Schema
        root_features = self.parse_node(self.schema, parent_name="", required_fields=self.schema.get("required", []), depth=0, local_stack_refs=[])
        
        for feat in root_features:
            self.uvl_lines.extend(render_feature(feat, indent=3))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.uvl_lines))
        print(f"✅ Modelo UVL generado: {output_path}")

    def parse_node(self, node, parent_name, required_fields, depth, local_stack_refs):
        """Recorrido en recursividad y en profundidad siguiendo el estilo de convert01.py"""
        if depth > 15: # Límite por seguridad
            return []
        
        features = []

        # 1. EVALUAR REFERENCIAS ($ref)
        if "$ref" in node:
            ref = node["$ref"]
            if ref in local_stack_refs:
                return [] # Evitar bucles circulares
            
            # Igual que en tu script: añadimos al stack y sacamos el nombre del último fragmento
            local_stack_refs.append(ref)
            ref_schema = self.resolve_reference(ref)
            
            if ref_schema:
                ref_name = sanitize(ref.split('/')[-1])
                feat_name = f"{parent_name}_{ref_name}" if parent_name else ref_name
                
                # Creamos la feature base usando el nombre de la referencia (ej: paths_Paths)
                feat = self._create_base_feature(ref_schema, feat_name, is_req=False)
                
                # Bajamos un nivel de profundidad
                feat["children"] = self.parse_node(ref_schema, feat_name, ref_schema.get("required", []), depth + 1, local_stack_refs)
                features.append(feat)
            
            local_stack_refs.pop()
            return features # Cuando hay $ref en JSON Schema no suele haber más propiedades al mismo nivel

        # 2. EVALUAR PROPIEDADES ESTÁTICAS (properties)
        if "properties" in node:
            reqs = node.get("required", [])
            for key, val_node in node["properties"].items():
                feat_name = f"{parent_name}_{sanitize(key)}" if parent_name else sanitize(key)
                is_req = key in reqs
                
                feat = self._create_base_feature(val_node, feat_name, is_req)
                
                # Llamada recursiva hacia el valor de la propiedad
                feat["children"] = self.parse_node(val_node, feat_name, [], depth + 1, local_stack_refs)
                features.append(feat)

        # 3. EVALUAR PROPIEDADES POR PATRÓN (patternProperties)
        # Aquí es donde se define paths y components.schemas
        if "patternProperties" in node:
            for pat, val_node in node["patternProperties"].items():
                if pat.startswith("^x-"): continue # Saltamos las extensiones x- de OpenAPI
                
                # Las patternProperties delegan su estructura al contenido (normalmente un $ref)
                sub_feats = self.parse_node(val_node, parent_name, [], depth + 1, local_stack_refs)
                # Al ser un patrón regex, el usuario puede instanciar 0 o N elementos, asignamos cardinalidad
                for sf in sub_feats:
                    sf["cardinality"] = "[0..*]"
                features.extend(sub_feats)

        # 4. EVALUAR PROPIEDADES ADICIONALES (additionalProperties)
        if "additionalProperties" in node:
            ap = node["additionalProperties"]
            if isinstance(ap, dict) and ap:
                sub_feats = self.parse_node(ap, parent_name, [], depth + 1, local_stack_refs)
                for sf in sub_feats:
                    sf["cardinality"] = "[0..*]"
                features.extend(sub_feats)

        # 5. EVALUAR ARRAYS (items)
        if node.get("type") == "array" and "items" in node:
            items = node["items"]
            if isinstance(items, dict) and items:
                sub_feats = self.parse_node(items, parent_name, [], depth + 1, local_stack_refs)
                for sf in sub_feats:
                    sf["cardinality"] = "[1..*]"
                features.extend(sub_feats)
                
        # 6. EVALUAR POLIMORFISMO (oneOf / anyOf)
        for choice_key in ["oneOf", "anyOf"]:
            if choice_key in node:
                for branch in node[choice_key]:
                    sub_feats = self.parse_node(branch, parent_name, [], depth + 1, local_stack_refs)
                    # Marcamos estas ramas para que se rendericen dentro de un grupo `alternative` en UVL
                    for sf in sub_feats:
                        sf["is_alternative"] = True
                    features.extend(sub_feats)
                    
        return features

    def _create_base_feature(self, node, name, is_req):
        """Inicializa el diccionario estándar de una característica"""
        raw_type = node.get("type", "").lower()
        
        # 1. FIX: MAPEO DE FLOAT/NUMBER -> INTEGER
        if raw_type in ["number", "integer"]:
            feat_type = "Integer"
        elif raw_type == "string":
            feat_type = "String"
        elif raw_type == "boolean":
            feat_type = ""
        else:
            feat_type = ""

        card = None
        if raw_type == "array":
            card = "[1..*]"

        return {
            "name": name,
            "type": feat_type,
            "description": node.get("description", ""),
            "default": node.get("default"),
            "enum": node.get("enum", []),
            "required": is_req,
            "children": [],
            "cardinality": card,
            "is_alternative": False
        }

# EJECUCIÓN DEL SCRIPT
if __name__ == "__main__":
    # Asegúrate de poner la ruta correcta a OpenAPI3_0.json
    parser = MetaSchema_UVL_Parser("../resources/OpenAPI3_0.json")
    parser.generate_uvl("../variability_model/fm_OpenAPI3_0.uvl")
    print("Script compilado: Extracción basada en tracking de $ref manual.")