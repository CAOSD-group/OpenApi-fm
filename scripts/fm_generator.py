import json
import os

def sanitize(name):
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

def clean_description(description: str) -> str:
    if not description: return ""
    return description.replace('\n', ' ').replace('`', '').replace('´', '').replace("'", "_").replace('{', '').replace('}', '').replace('"', '').replace("\\", "_")

def render_feature(entry, indent=2):
    i = "\t" * indent
    lines = []

    typename = entry.get("type", "")
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
    
    # 1. CARDINALIDAD APLICADA DIRECTAMENTE AL NODO ARRAY O MAPA
    if entry.get("cardinality"):
        lines.append(f"{i}{name} cardinality {entry['cardinality']}{attr_str}")
    else:
        # Tipos primitivos (String, Integer, Boolean)
        if typename and typename != 'Boolean' and not enum:
            lines.append(f"{i}{typename} {name}{attr_str}")
        else:
            lines.append(f"{i}{name}{attr_str}")
            
    if enum:
        lines.append(i + "\talternative")
        for val in enum:
            enum_val = sanitize(f"{name}_{val}")
            lines.append(f"{i}\t\t{enum_val} {{doc 'Specific value: {sanitize(str(val))}'}}")

    if children:
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
        parts = ref.strip('#/').split('/')
        schema_node = self.schema
        try:
            for part in parts:
                schema_node = schema_node.get(part, {})
                if not schema_node:
                    return None
            return schema_node
        except Exception:
            return None

    def generate_uvl(self, output_path):
        self.uvl_lines = [
            "namespace OpenAPI_3_0_Specification", 
            "features", 
            "\tOpenAPI_Document {abstract, doc 'Root of an OpenAPI v3.0.x Document'}", 
            "\t\tmandatory"
        ]

        # Iniciamos el parseo desde la raíz del documento
        root_features = self.parse_node(self.schema, parent_name="", local_stack_refs=[], depth=0)
        
        for feat in root_features:
            # Propagamos la obligatoriedad explícita de la raíz (openapi, info, paths)
            feat["required"] = feat["name"] in self.schema.get("required", [])
            self.uvl_lines.extend(render_feature(feat, indent=3))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.uvl_lines))
        print(f"✅ Modelo UVL generado: {output_path}")

    def parse_node(self, node, parent_name, local_stack_refs, depth):
        if depth > 15: return []
        features = []

        # 1. RESOLUCIÓN TRANSPARENTE DE $REF (No crea nodos "basura")
        if "$ref" in node:
            ref = node["$ref"]
            if ref in local_stack_refs: return [] 
            
            local_stack_refs.append(ref)
            resolved = self.resolve_reference(ref)
            if resolved:
                # Extraemos los hijos directamente del esquema resuelto y los devolvemos. 
                # Así se cuelgan del nodo que invocó la referencia original.
                res = self.parse_node(resolved, parent_name, local_stack_refs, depth + 1)
                local_stack_refs.pop()
                return res
            local_stack_refs.pop()
            return []

        # 2. PROPIEDADES DIRECTAS (properties)
        if "properties" in node:
            reqs = node.get("required", [])
            for key, val_node in node["properties"].items():
                feat_name = f"{parent_name}_{sanitize(key)}" if parent_name else sanitize(key)
                is_req = key in reqs
                
                feat = self._create_base_feature(val_node, feat_name, is_req)
                feat["children"] = self.parse_node(val_node, feat_name, local_stack_refs, depth + 1)
                features.append(feat)

        # 3. RUTAS Y ESQUEMAS DINÁMICOS (patternProperties)
        if "patternProperties" in node:
            for pat, val_node in node["patternProperties"].items():
                if pat.startswith("^x-"): continue 
                
                feat_name = f"{parent_name}_DynamicKey" if parent_name else "DynamicKey"
                # Le pasamos el propio val_node para que detecte si es array
                feat = self._create_base_feature(val_node, feat_name, is_req=False)
                feat["cardinality"] = "[0..*]" # Forzamos mapa dinámico
                feat["description"] = f"Dynamic keys matching regex: {pat}. {feat['description']}"
                
                feat["children"] = self.parse_node(val_node, feat_name, local_stack_refs, depth + 1)
                features.append(feat)

        # 4. EL CASO SECURITYREQUIREMENT Y MAPAS (additionalProperties)
        if "additionalProperties" in node:
            ap = node["additionalProperties"]
            if isinstance(ap, dict) and ap:
                feat_name = f"{parent_name}_MapEntry" if parent_name else "MapEntry"
                feat = self._create_base_feature({}, feat_name, is_req=False)
                feat["cardinality"] = "[0..*]" # Es un mapa
                feat["description"] = "Dynamic map entry"
                
                # Si el valor del mapa es un array (Caso SecurityRequirement)
                if ap.get("type") == "array":
                    arr_name = f"{feat_name}_Array"
                    arr_feat = self._create_base_feature(ap, arr_name, is_req=True) # Este recibe el [1..*]
                    arr_feat["children"] = self.parse_node(ap, arr_name, local_stack_refs, depth + 1)
                    feat["children"].append(arr_feat)
                else:
                    # Si el valor es un objeto normal o primitivo
                    feat["children"] = self.parse_node(ap, feat_name, local_stack_refs, depth + 1)
                
                features.append(feat)

        # 5. ELEMENTOS DE UN ARRAY (items)
        if node.get("type") == "array" and "items" in node:
            items = node["items"]
            if isinstance(items, dict) and items:
                # Si es un array de primitivos (Strings, Ints...) sin sub-propiedades
                if items.get("type") in ["string", "integer", "number", "boolean"] and not "properties" in items:
                    t_name = items.get("type").capitalize()
                    if t_name == "Number": t_name = "Integer"
                    child_name = f"{parent_name}_{t_name}Value"
                    child_feat = self._create_base_feature(items, child_name, is_req=True)
                    features.append(child_feat)
                else:
                    # Si es un array de objetos (ej: servers_Server), expandimos las propiedades 
                    # y las colgamos directamente como hijos del Array.
                    sub_feats = self.parse_node(items, parent_name, local_stack_refs, depth + 1)
                    for sf in sub_feats: 
                        sf["required"] = sf.get("required", False) # Mantienen su obligatoriedad original
                    features.extend(sub_feats)
                
        # 6. POLIMORFISMO (oneOf / anyOf)
        for choice_key in ["oneOf", "anyOf"]:
            if choice_key in node:
                for i, branch in enumerate(node[choice_key]):
                    opt_name = f"{parent_name}_{choice_key}Option{i+1}"
                    opt_feat = self._create_base_feature(branch, opt_name, is_req=False)
                    opt_feat["is_alternative"] = True
                    opt_feat["children"] = self.parse_node(branch, opt_name, local_stack_refs, depth + 1)
                    features.append(opt_feat)
                    
        return features

    def _create_base_feature(self, node, name, is_req):
        raw_type = node.get("type", "").lower()
        
        # 2. MAPEO RIGUROSO DE TIPOS: float/number -> Integer
        if raw_type in ["number", "integer"]:
            feat_type = "Integer"
        elif raw_type == "string":
            feat_type = "String"
        elif raw_type == "boolean":
            feat_type = "Boolean"
        else:
            feat_type = ""

        # 3. LA CARDINALIDAD SE ASIGNA AL PROPIO NODO
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
    parser.generate_uvl("../variability_model/fm_OpenAPI3_0_1_v2.uvl")
    print("Script compilado: Extracción basada en tracking de $ref manual.")