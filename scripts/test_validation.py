import os, json
from flamapy.metamodels.fm_metamodel.transformations import UVLReader
from flamapy.metamodels.pysat_metamodel.transformations import FmToPysat
from flamapy.metamodels.pysat_metamodel.operations import PySATSatisfiableConfiguration
from flamapy.metamodels.configuration_metamodel.models import Configuration

# Importamos el Lector Simple que creamos en el paso anterior
from simple_reader_configsOpenAPI import SimpleAutomatedOpenAPIReader

def get_all_parents(feature):
    parent = feature.get_parent()
    return [] if parent is None else [parent.name] + get_all_parents(parent)

def get_all_mandatory_children(feature):
    children = []
    for child in feature.get_children():
        if child.is_mandatory():
            children.append(child.name)
            children.extend(get_all_mandatory_children(child))
    return children

def complete_configuration(configuration: Configuration, fm_model) -> Configuration:
    """Rellena los padres y mandatory children obligatorios para que Flamapy no falle"""
    configs_elements = dict(configuration.elements)
    for element in configuration.get_selected_elements():
        feature = fm_model.get_feature_by_name(element)
        if feature is None:
            raise Exception(f'Error: el elemento "{element}" no está presente en el modelo UVL.')
            
        children = {child: True for child in get_all_mandatory_children(feature)}
        parents = {parent: True for parent in get_all_parents(feature)}
        
        for parent in parents:
            parent_feature = fm_model.get_feature_by_name(parent)
            parent_children = get_all_mandatory_children(parent_feature)
            children.update({child: True for child in parent_children})
            
        configs_elements.update(children)
        configs_elements.update(parents)
    return Configuration(configs_elements)

def valid_config_version_json(configuration, fm_model, sat_model):
    """Valida la configuración contra el solver SAT"""
    config = complete_configuration(configuration, fm_model)
    config.set_full(True)
    
    satisfiable_op = PySATSatisfiableConfiguration() 
    satisfiable_op.set_configuration(config)
    
    return satisfiable_op.execute(sat_model).get_result(), config.get_selected_elements()


if __name__ == '__main__':
    # 1. Configura tus rutas aquí
    UVL_PATH = "../variability_model/fm_OpenAPI3_0_1_v3.uvl" # Cambia al nombre de tu UVL
    YAML_PATH = "../resources/petstore.yaml"
    RULES_PATH = "openapi_extraction_rules.json"

    print("1. Cargando Modelo UVL y traduciendo a SAT...")
    fm_model = UVLReader(UVL_PATH).transform()
    sat_model = FmToPysat(fm_model).transform()

    print("\n2. Leyendo YAML con el Lector Automatizado (Versión Simple)...")
    from simple_reader_configsOpenAPI import SimpleAutomatedOpenAPIReader
    reader = SimpleAutomatedOpenAPIReader(YAML_PATH, RULES_PATH)
    configurations = reader.transform()
    
    config_cero = configurations[0]
    print(f"   -> Características base extraídas: {len(config_cero.elements)}")

    print("\n3. Completando y Validando Configuración en Flamapy...")
    try:
        # Completamos la configuración manualmente para poder guardarla antes de validar
        config_completa = complete_configuration(config_cero, fm_model)
        config_completa.set_full(True)
        
        # --- NUEVO: GUARDAR LA CONFIGURACIÓN EN UN ARCHIVO ---
        elementos_activos = config_completa.get_selected_elements()
        with open("debug_config.json", "w", encoding="utf-8") as f:
            # Lo ordenamos alfabéticamente para que sea fácil de leer
            json.dump(sorted(elementos_activos), f, indent=4)
        print("   -> 📁 Configuración completa guardada en 'debug_config.json' para inspección.")
        # -----------------------------------------------------

        # Validamos
        satisfiable_op = PySATSatisfiableConfiguration() 
        satisfiable_op.set_configuration(config_completa)
        valid = satisfiable_op.execute(sat_model).get_result()
        
        if valid:
            print("\n✅ RESULTADO: Valid?: True")
            print("¡Enhorabuena! El mapeo base funciona perfectamente.")
        else:
            print("\n❌ RESULTADO: Valid?: False")
            print("El SAT solver detectó una inconsistencia. Revisa 'debug_config.json'.")
            
    except Exception as e:
        print(f"\n❌ ERROR FATAL DURANTE LA VALIDACIÓN: {e}")