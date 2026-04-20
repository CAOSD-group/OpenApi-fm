import os
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
    UVL_PATH = "../variability_model/fm_OpenAPI3_0_1_v2.uvl" # Cambia al nombre de tu UVL
    
    YAML_PATH = "../resources/petstore.yaml"
    RULES_PATH = "openapi_extraction_rules.json"

    print("1. Cargando Modelo UVL y traduciendo a SAT...")
    fm_model = UVLReader(UVL_PATH).transform()
    sat_model = FmToPysat(fm_model).transform()

    print("\n2. Leyendo YAML con el Lector Automatizado (Versión Simple)...")
    # Este lector mapea directamente el YAML a características usando las reglas
    reader = SimpleAutomatedOpenAPIReader(YAML_PATH, RULES_PATH)
    configurations = reader.transform()
    
    # Tomamos SOLO la primera configuración generada (la de prueba)
    config_cero = configurations[0]
    print(f"   -> Características base extraídas: {len(config_cero.elements)}")

    print("\n3. Completando y Validando Configuración en Flamapy...")
    try:
        valid, complete_config = valid_config_version_json(config_cero, fm_model, sat_model)
        
        if valid:
            print("\n✅ RESULTADO: Valid?: True")
            print("¡Enhorabuena! El mapeo base y el aplanado de variables funcionan perfectamente con el UVL.")
        else:
            print("\n❌ RESULTADO: Valid?: False")
            print("El SAT solver detectó una inconsistencia. Hay que revisar si falta seleccionar alguna rama 'alternative'.")
            
    except Exception as e:
        print(f"\n❌ ERROR FATAL DURANTE LA VALIDACIÓN: {e}")