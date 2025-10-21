# diagnostico_cuentas.py
import requests
import json
from core_poster import construir_proxies, construir_cookie_header

def diagnosticar_cuenta(cuenta):
    """Diagnóstico completo de una cuenta"""
    nombre = cuenta.get("nombre", "Sin nombre")
    print(f"\n🔍 Diagnosticando cuenta: {nombre}")
    
    # 1. Verificar cookies básicas
    cookies = cuenta.get("cookies", {})
    required = ["csrftoken", "sessionid", "ds_user_id"]
    missing = [k for k in required if k not in cookies]
    
    if missing:
        print(f"❌ Faltan cookies: {missing}")
        return False
    
    print(f"✅ Cookies básicas presentes")
    
    # 2. Verificar redirección
    proxy = construir_proxies(cuenta.get("proxy"))
    cookie_header = construir_cookie_header(cookies)
    
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "cookie": cookie_header,
    }
    
    try:
        response = requests.get(
            "https://www.threads.net/",
            headers=headers,
            proxies=proxy,
            verify=False,
            allow_redirects=True,
            timeout=15
        )
        
        print(f"📍 URL final: {response.url}")
        print(f"📊 Status code: {response.status_code}")
        
        if "threads.com" in response.url:
            print("ℹ️  Redirección a threads.com detectada")
            
            # Verificar si es accesible
            if response.status_code == 200:
                print("✅ threads.com es accesible - puede ser redirección regional")
                return False
            else:
                print("❌ threads.com no accesible - cookies probablemente inválidas")
                return False
        else:
            print("✅ Acceso directo a threads.net exitoso")
            return True
            
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return False

# Usar el diagnóstico
if __name__ == "__main__":
    with open("cuentas.json", "r", encoding="utf-8") as f:
        cuentas = json.load(f)
    
    for cuenta in cuentas:
        if cuenta.get("enabled", True):
            diagnosticar_cuenta(cuenta)