import json
from pathlib import Path

# Importaciones de FLAMAPY
from flamapy.metamodels.fm_metamodel.transformations import UVLReader
from flamapy.metamodels.pysat_metamodel.transformations import FmToPysat
from flamapy.metamodels.pysat_metamodel.operations import PySATSatisfiableConfiguration
from flamapy.metamodels.configuration_metamodel.models import Configuration

class OpenAPIValidator:
    def __init__(self, uvl_path: str):
        print(f"Cargando Modelo UVL desde: {uvl_path}")
        # 1. Leemos el Feature Model
        self.fm = UVLReader(uvl_path).transform()
        # 2. Lo traducimos al modelo matemático (SAT)
        self.sat_model = FmToPysat(self.fm).transform()
        
    def flatten_config(self, data) -> dict:
        """
        Algoritmo recursivo para aplanar el JSON jerárquico en un diccionario 
        plano que FLAMAPY pueda entender: {"feature_name": True, ...}
        """
        flat_elements = {}
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, bool) and value:
                    flat_elements[key] = True
                elif isinstance(value, (str, int, float)):
                    # Guardamos el valor por si FLAMAPY usa atributos
                    flat_elements[key] = value
                elif isinstance(value, dict):
                    flat_elements[key] = True
                    flat_elements.update(self.flatten_config(value))
                elif isinstance(value, list):
                    # Es un array de objetos (ej. múltiples endpoints o schemas)
                    flat_elements[key] = True
                    for item in value:
                        flat_elements.update(self.flatten_config(item))
                        
        return flat_elements

    def validate_json(self, json_path: str) -> bool:
        print(f"\nAnalizando Configuración: {json_path}")
        
        # 1. Leer el JSON generado por nuestro mapper
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
            
        # 2. Aplanar la configuración
        flat_elements = self.flatten_config(json_data)
        
        # Opcional: Asegurarse de que los valores String/Integer estén bien mapeados para tu versión de Flamapy
        # Si Flamapy exige booleanos estrictos para la estructura:
        boolean_elements = {k: True for k in flat_elements.keys()}
        
        # 3. Crear el objeto Configuration de FLAMAPY
        config = Configuration(elements=boolean_elements)
        
        print(f"Características activadas a evaluar: {len(boolean_elements)}")
        
        # 4. Ejecutar la operación de Validación SAT
        operation = PySATSatisfiableConfiguration(config)
        operation.execute(self.sat_model)
        
        is_valid = operation.get_result()
        
        if is_valid:
            print("✅ RESULTADO: La configuración es VÁLIDA y cumple con el estándar OpenAPI.")
        else:
            print("❌ RESULTADO: La configuración es INVÁLIDA.")
            # Si es inválida, en un futuro podemos usar la operación PySATProducts 
            # o PySATCoreFeatures para diagnosticar qué falló.
            
        return is_valid

if __name__ == '__main__':
    # Rutas a tus archivos generados
    UVL_FILE = "../variability_model/openapi_standard_model.uvl"
    JSON_CONFIG_FILE = "../resources/petstore_config.json"
    
    validator = OpenAPIValidator(UVL_FILE)
    validator.validate_json(JSON_CONFIG_FILE)