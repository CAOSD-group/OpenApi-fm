import json
import os

def sanitize(name):
    """Limpia los caracteres especiales para el formato UVL"""
    if not name: return "Unknown"
    return str(name).replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_").replace("{", "").replace("}", "").replace("$", "")

def clean_description(description: str) -> str:
    if not description: return ""
    return description.replace('\n', ' ').replace('`', '').replace('´', '').replace("'", "_").replace('{', '').replace('}', '').replace('"', '')#.replace("\\", "_")

def render_feature(entry, indent=2):
    """Renderiza el nodo a sintaxis estricta UVL"""
    i = "\t" * indent
    lines = []

    typename = entry.get("type", "")
    name = sanitize(entry["name"])
    doc = entry.get("description", "")
    default = entry.get("default")
    enum = entry.get("enum", [])
    pattern = entry.get("pattern")
    children = entry.get("children", [])

    attributes = []
    
    # Inyección del nuevo atributo PATTERN para diccionarios
    if pattern:
        safe_pat = pattern.replace("'", "\\'")
        attributes.append(f"pattern '{safe_pat}'")
        
    if default is not None:
        val = str(default).lower() if isinstance(default, bool) else f"'{default}'"
        attributes.append(f'default {val}')
        
    if doc:
        attributes.append(f"doc '{clean_description(doc.strip())}'")

    attr_str = f" {{{', '.join(attributes)}}}" if attributes else ""
    
    # Cardinalidad aplicada directamente
    if entry.get("cardinality"):
        lines.append(f"{i}{name} cardinality {entry['cardinality']}{attr_str}")
    else:
        if typename and typename != 'Boolean' and not enum:
            lines.append(f"{i}{typename} {name}{attr_str}")
        else:
            lines.append(f"{i}{name}{attr_str}")
            
    if enum and len(enum) > 1:
        
        lines.append(i + "\talternative")
        for val in enum:
            enum_val = sanitize(f"{name}_{val}")
            lines.append(f"{i}\t\t{enum_val} {{doc 'Specific value: {sanitize(str(val))}'}}")
    elif enum and len(enum) == 1:
        # Si solo hay un valor en el enum, lo tratamos como un default implícito
        #print(f"Enumeration detected for {name}: {enum}")
        val = enum[0]
        lines.append(i + "\toptional")
        #val_str = str(val).lower() if isinstance(val, bool) else f"'{val}'"
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
                if not schema_node: return None
            return schema_node
        except Exception:
            return None

    def generate_uvl(self, output_path):
        self.uvl_lines = [
            "namespace OpenAPI_3_0_Specification", 
            "features", 
            "\tOpenAPI_Document {abstract, doc 'Root of an OpenAPI v3.0.x Document'}"
        ]

        # Iniciar extracción
        root_features = self.parse_node(self.schema, parent_name="", local_stack_refs=[], depth=0)
        
        # Separación estricta de mandatory/optional de la raíz (Soluciona el error anterior)
        mand = []
        opt = []
        root_reqs = self.schema.get("required", [])
        
        for feat in root_features:
            feat["required"] = feat["name"] in root_reqs
            if feat["required"]:
                mand.append(feat)
            else:
                opt.append(feat)

        if mand:
            self.uvl_lines.append("\t\tmandatory")
            for feat in mand:
                self.uvl_lines.extend(render_feature(feat, indent=3))
                
        if opt:
            self.uvl_lines.append("\t\toptional")
            for feat in opt:
                self.uvl_lines.extend(render_feature(feat, indent=3))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.uvl_lines))
        print(f"✅ Modelo UVL generado: {output_path}")

    def parse_node(self, node, parent_name, local_stack_refs, depth):
        if depth > 50: return []
        features = []

        # 1. RESOLUCIÓN TRANSPARENTE DE $REF
        if "$ref" in node:
            ref = node["$ref"]
            if ref in local_stack_refs: return [] 
            
            local_stack_refs.append(ref)
            resolved = self.resolve_reference(ref)
            if resolved:
                res = self.parse_node(resolved, parent_name, local_stack_refs, depth + 1)
                local_stack_refs.pop()
                return res
            local_stack_refs.pop()
            return []

        # 2. PROPIEDADES DIRECTAS
        if "properties" in node:
            reqs = node.get("required", [])
            for key, val_node in node["properties"].items():
                feat_name = f"{parent_name}_{sanitize(key)}" if parent_name else sanitize(key)
                is_req = key in reqs
                
                feat = self._create_base_feature(val_node, feat_name, is_req)
                feat["children"] = self.parse_node(val_node, feat_name, local_stack_refs, depth + 1)
                features.append(feat)

        # 3. MAPAS POR PATRÓN (patternProperties)
        if "patternProperties" in node:
            for pat, val_node in node["patternProperties"].items():
                # Ignoramos la extensión ^x- como acordamos
                if pat.startswith("^x-"): continue 
                # --- FIX: Interceptar el "hack" de JSON Schema para la propiedad $ref literal ---
                if pat == "^\\$ref$":
                    feat_name = f"{parent_name}_ref" if parent_name else "ref"
                    is_req = "$ref" in node.get("required", [])
                    ref_feat = self._create_base_feature(val_node, feat_name, is_req)
                    ref_feat["type"] = "String"
                    features.append(ref_feat)
                    continue                
                # Procesamos el valor del diccionario de forma aplanada
                feat = self._process_map_value(val_node, parent_name, local_stack_refs, depth + 1, pat=pat)
                if feat: features.append(feat)

        # 4. MAPAS DINÁMICOS (additionalProperties)
        if "additionalProperties" in node:
            ap = node["additionalProperties"]
            if isinstance(ap, dict) and ap:
                feat = self._process_map_value(ap, parent_name, local_stack_refs, depth + 1)
                if feat: features.append(feat)

        # 5. ARRAYS (items)
        if node.get("type") == "array" and "items" in node:
            items = node["items"]
            if isinstance(items, dict) and items:
                if items.get("type") in ["string", "integer", "number", "boolean"] and not "properties" in items:
                    t_name = items.get("type").capitalize()
                    if t_name == "Number": t_name = "Integer"
                    child_name = f"{parent_name}_{t_name}Value"
                    child_feat = self._create_base_feature(items, child_name, is_req=True)
                    features.append(child_feat)
                else:
                    sub_feats = self.parse_node(items, parent_name, local_stack_refs, depth + 1)
                    for sf in sub_feats: sf["required"] = sf.get("required", False) 
                    features.extend(sub_feats)
                
        # 6. POLIMORFISMO (oneOf / anyOf)
        # 6. POLIMORFISMO SEMÁNTICO (oneOf / anyOf)
        for choice_key in ["oneOf", "anyOf"]:
            if choice_key in node:
                for i, branch in enumerate(node[choice_key]):
                    
                    # --- NUEVA LÓGICA DE EXTRACCIÓN DE NOMBRES ---
                    if "$ref" in branch:
                        branch_name = sanitize(branch["$ref"].split('/')[-1])
                        
                    # CASO 3: Tiene descripción (ej. "Bearer" o "Non Bearer")
                    elif "description" in branch:
                        # Cogemos las primeras palabras de la descripción para el nombre
                        desc_snippet = branch["description"].split(',')[0][:30]
                        branch_name = sanitize(desc_snippet)
                        
                    # CASO 2: Tiene validaciones "required" (ej. SchemaXORContent)
                    elif "required" in branch and isinstance(branch["required"], list):
                        req_keys = "_".join([sanitize(r) for r in branch["required"]])
                        branch_name = f"Requires_{req_keys}"
                        
                    elif "type" in branch:
                        branch_name = sanitize(branch["type"].capitalize())
                        
                    else:
                        # Fallback final si es una regla muy extraña
                        branch_name = f"Option_{i+1}"
                        
                    opt_name = f"{parent_name}_{branch_name}" if parent_name else branch_name
                    
                    opt_feat = self._create_base_feature(branch, opt_name, is_req=False)
                    opt_feat["is_alternative"] = True
                    opt_feat["children"] = self.parse_node(branch, opt_name, local_stack_refs, depth + 1)
                    features.append(opt_feat)
                    
        return features

    def _process_map_value(self, val_node, parent_name, local_stack_refs, depth, pat=None):
        """Maneja la fusión del diccionario: Clave (KeyValue) + Valor + [0..*]"""
        resolved_node = val_node
        ref_name_part = None
        
        # Resolvemos la referencia para conocer el tipo y el nombre
        if "$ref" in val_node:
            ref = val_node["$ref"]
            if ref in local_stack_refs:
                print(f"⚠️ Referencia cíclica detectada en {ref}, {parent_name} omitiendo para evitar bucle infinito.")
                return None
            resolved_node = self.resolve_reference(ref)
            if not resolved_node: return None
            ref_name_part = sanitize(ref.split('/')[-1])
            local_stack_refs.append(ref)
            
        raw_type = resolved_node.get("type", "").lower()
        
        # CASO 1: El valor del diccionario es un Array (No se pueden fusionar cardinalidades [0..*] y [1..*])
        if raw_type == "array":
            wrapper_name = f"{parent_name}_{ref_name_part}" if ref_name_part else f"{parent_name}_MapEntry"
            wrapper_feat = self._create_base_feature({}, wrapper_name, is_req=False)
            wrapper_feat["cardinality"] = "[0..*]"
            if pat: wrapper_feat["pattern"] = pat # Guardamos el regex
                
            # Clave inyectada
            key_feat = self._create_base_feature({}, f"{wrapper_name}_KeyValue", is_req=True)
            key_feat["type"] = "String"
            wrapper_feat["children"].append(key_feat)
            
            # Valor (Array con [1..*])
            arr_name = f"{wrapper_name}_Array"
            arr_feat = self._create_base_feature(resolved_node, arr_name, is_req=True) 
            arr_feat["children"] = self.parse_node(resolved_node, arr_name, local_stack_refs, depth + 1)
            wrapper_feat["children"].append(arr_feat)
            
            if "$ref" in val_node: local_stack_refs.pop()
            return wrapper_feat
            
        # CASO 2: El valor es un Objeto o Primitivo (FUSIÓN PERFECTA)
        else:
            feat_name = f"{parent_name}_{ref_name_part}" if ref_name_part else f"{parent_name}_Value"
            feat = self._create_base_feature(resolved_node, feat_name, is_req=False)
            feat["cardinality"] = "[0..*]" # Le asignamos que el objeto se puede instanciar de 0 a N veces
            if pat: feat["pattern"] = pat # Guardamos el regex
            
            # Clave inyectada en el propio objeto
            key_feat = self._create_base_feature({}, f"{feat_name}_KeyValue", is_req=True)
            key_feat["type"] = "String"
            feat["children"].append(key_feat)
            
            # Y directamente colgamos las propiedades del objeto (get, put, post, etc.)
            feat["children"].extend(self.parse_node(resolved_node, feat_name, local_stack_refs, depth + 1))
            
            if "$ref" in val_node: local_stack_refs.pop()
            return feat

    def _create_base_feature(self, node, name, is_req):
        raw_type = node.get("type", "").lower()
        
        if raw_type in ["number", "integer"]: feat_type = "Integer"
        elif raw_type == "string": feat_type = "String"
        elif raw_type == "boolean": feat_type = "Boolean"
        else: feat_type = ""

        # Los objetos no tienen cardinalidad intrínseca, solo los arrays.
        # Los diccionarios obtienen su [0..*] en la función _process_map_value
        card = "[1..*]" if raw_type == "array" else None

        return {
            "name": name,
            "type": feat_type,
            "description": node.get("description", ""),
            "default": node.get("default"),
            "enum": node.get("enum", []),
            "required": is_req,
            "children": [],
            "cardinality": card,
            "is_alternative": False,
            "pattern": None
        }

if __name__ == "__main__":
    # Sustituye por la ruta a tu testing.json
    parser = MetaSchema_UVL_Parser("../resources/OpenAPI3_0.json")
    parser.generate_uvl("../variability_model/fm_OpenAPI3_0_1_v2.uvl")
    print("Mapeo completado.")