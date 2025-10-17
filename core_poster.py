# core_poster.py
import requests
import json
import os
import time
import threading
import random
import urllib3
import sys
from datetime import datetime
from pathlib import Path
# Importaciones necesarias para manejo de imagen si tu código original las usaba
# from PIL import Image
# import io 

# Suprime advertencias de SSL/InsecureRequestWarning (útil con proxies)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Control de Ejecución para la GUI ---
IS_RUNNING = False
# 🟢 CORRECCIÓN: Se restauran las claves de DELAY_CONFIG esperadas por la GUI.
DELAY_CONFIG = {  # CONFIGURACIÓN GLOBAL DE DELAY
    "min_minutes": 17,  # 1 hora por defecto
    "max_minutes": 33,  # 2.5 horas por defecto
    "jitter": 3,        # Jitter por defecto (variación aleatoria)
    "use_individual_delays": False  # CLAVE FALTANTE: Inicializada a False (usa delay general)
}

def set_running_status(status):
    """Establece la bandera global de estado."""
    global IS_RUNNING
    IS_RUNNING = status
    
    
def get_running_status():
    """Retorna el estado actual de la bandera IS_RUNNING."""
    return IS_RUNNING


def update_delay_config(min_min, max_min, use_individual_delays):
    """Actualiza los parámetros de delay global desde la GUI."""
    global DELAY_CONFIG

    try:
        min_min_int = int(min_min)
        max_min_int = int(max_min)
    except ValueError:
        return

    if min_min_int > max_min_int:
        min_min_int, max_min_int = max_min_int, min_min_int

    DELAY_CONFIG["min_minutes"] = max(1, min_min_int)
    DELAY_CONFIG["max_minutes"] = max(1, max_min_int)
    # 🟢 Se añade la clave use_individual_delays que faltaba
    DELAY_CONFIG["use_individual_delays"] = use_individual_delays

    print(
        f"⚙️ Configuración de delay actualizada: {DELAY_CONFIG['min_minutes']} - {DELAY_CONFIG['max_minutes']} minutos. Modo Individual: {DELAY_CONFIG['use_individual_delays']}")


# 🟢 FUNCIÓN DE DELAY FALTANTE (Restaurada para compatibilidad)
def get_post_delay(post, grupo_nombre):
    """
    Determina el delay para un post basado en la configuración.
    Prioridad: Delay individual > Delay grupal > Delay global
    """
    min_global = DELAY_CONFIG.get("min_minutes", 17)
    max_global = DELAY_CONFIG.get("max_minutes", 33)
    jitter = DELAY_CONFIG.get("jitter", 3)

    # 1. Delay Individual (Si está habilitado y el post tiene las claves)
    if DELAY_CONFIG["use_individual_delays"] and post.get('delay_min') is not None and post.get('delay_max') is not None:
        try:
            delay_min = int(post['delay_min'])
            delay_max = int(post['delay_max'])
            if delay_min > 0 and delay_max >= delay_min:
                return random.randint(delay_min, delay_max)
        except ValueError:
            pass # Continúa al siguiente nivel si hay error de tipo
    
    # 2. Delay Grupal (Si la configuración existe a nivel de grupo, aunque no la estamos manejando aquí)
    # [Lógica de delay grupal omitida si no está definida en otra parte de tu script]

    # 3. Delay Global (Default)
    delay_base = random.randint(min_global, max_global)
    delay_jitter = random.randint(-jitter, jitter)
    final_delay = max(1, delay_base + delay_jitter)
    return final_delay


def interruptible_sleep(duration_seconds):
    """
    Duerme por la duración especificada, pero verifica cada 1 segundo si el bot debe detenerse.
    Retorna True si la espera terminó, False si fue interrumpida por la señal de stop.
    """
    check_interval = 1 # Verificar cada segundo
    
    for _ in range(int(duration_seconds / check_interval)):
        if not get_running_status():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Detención inmediata solicitada. Saliendo de la espera.")
            return False 
        time.sleep(check_interval)
        
    remaining_time = duration_seconds % check_interval
    if remaining_time > 0:
        time.sleep(remaining_time)
        
    return get_running_status() 

# --- Variables Globales y Utilerías ---
CUENTAS_PATH = "cuentas.json"
FALLOS_PATH = "fallos.json"

# --- Control de Fallos Globales y Thread-Safe ---
FALLOS_EN_MEMORIA = []
FALLOS_LOCK = threading.Lock() # Lock para acceso thread-safe a FALLOS_EN_MEMORIA
CUENTAS_LOCK = threading.Lock() # Lock para acceso thread-safe a cuentas.json

if not os.path.exists(FALLOS_PATH):
    with open(FALLOS_PATH, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

if not os.path.exists(CUENTAS_PATH):
    with open(CUENTAS_PATH, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)


def cargar_json(path):
    """Carga datos de un archivo JSON de forma segura."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if data is None:
                return []
            return data
        except json.JSONDecodeError:
            print(f"❌ Error leyendo {path}: JSON mal formado.")
            return []
        except Exception as e:
            print(f"❌ Error general al cargar {path}: {e}")
            return []


def calcular_jazoest(csrftoken):
    return f"2{sum(ord(c) for c in csrftoken)}"


def generar_upload_id():
    return str(int(time.time() * 1000))


def construir_cookie_header(cookies):
    orden = ["mid", "ig_did", "csrftoken", "ds_user_id", "sessionid", "rur"]
    return "; ".join([f"{k}={cookies[k]}" for k in orden if k in cookies])


def construir_proxies(proxy_str):
    """Construye el diccionario de proxies o retorna None si no es válido."""
    if not proxy_str:
        return None
    try:
        if '@' not in proxy_str:
            return {
                "http": f"http://{proxy_str}",
                "https": f"http://{proxy_str}"
            }

        userpass, hostport = proxy_str.split("@")
        return {
            "http": f"http://{userpass}@{hostport}",
            "https": f"http://{userpass}@{hostport}"
        }
    except ValueError:
        print(
            f"❌ Error de formato en proxy: {proxy_str}. Debe ser user:pass@host:port.")
        return None

# FUNCIÓN DE VERIFICACIÓN (Mantenida, pero no usada en run_posting_threads para evitar bloqueos)
def verificar_estado_cuenta(cuenta):
    """
    Verifica si las cookies están activas haciendo una petición al home de Threads.
    Retorna True si es válida, False si requiere login o hay fallo de conexión.
    """
    nombre = cuenta.get("nombre", "(sin nombre)")
    proxy = construir_proxies(cuenta.get("proxy"))
    
    try:
        cookies = cuenta["cookies"]
        cookie_header = construir_cookie_header(cookies)
        csrf_token = cookies["csrftoken"]

        headers = {
            "x-instagram-ajax": "0", "x-csrftoken": csrf_token, "x-ig-app-id": "238260118697367",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "cookie": cookie_header, "accept": "*/*",
            "accept-language": "en-US,en;q=0.9", "cache-control": "max-age=0",
        }
        
        response = requests.get(
            "https://www.threads.net/",
            headers=headers,
            proxies=proxy,
            verify=False,
            timeout=30,
            allow_redirects=False # CLAVE para detectar 301/302/307
        )
        
        # Lógica de Redirección (301, 302, 307)
        if response.status_code in [301, 302, 307]:
            return False
            
        if response.status_code == 200 and "threads.net" in response.url:
            return True
        else:
            return False
            
    # Lógica de Fallo de Conexión/Proxy en Verificación
    except requests.exceptions.ProxyError:
        return False
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


# --- Funciones de Gestión de Fallos y Cuentas ---

def agregar_fallo_en_memoria(nombre_cuenta, post_index, error_msg):
    """
    Añade un fallo a la lista global en memoria de forma thread-safe.
    """
    with FALLOS_LOCK: # Bloqueo de acceso
        FALLOS_EN_MEMORIA.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nombre": nombre_cuenta,
            "post": post_index,
            "error_msg": error_msg
        })


def guardar_fallos_periodicamente():
    """
    Hilo para guardar los fallos en disco de forma segura.
    Lee los fallos existentes, añade los nuevos de memoria y los guarda.
    """
    global FALLOS_EN_MEMORIA, FALLOS_LOCK
    
    while get_running_status(): 
        if not interruptible_sleep(180): # Espera 3 minutos (180s) de forma interrumpible
            break 
            
        with FALLOS_LOCK:
            if FALLOS_EN_MEMORIA:
                fallos_existentes = [] 
                
                if os.path.exists(FALLOS_PATH):
                    try:
                        with open(FALLOS_PATH, "r", encoding='utf-8') as f:
                            fallos_existentes = json.load(f)
                    except json.JSONDecodeError:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Advertencia: fallos.json corrupto. Los fallos anteriores se han perdido.")
                    except Exception as e:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ERROR desconocido al cargar fallos.json: {e}")

                fallos_existentes.extend(FALLOS_EN_MEMORIA)
                FALLOS_EN_MEMORIA.clear()

                try:
                    with open(FALLOS_PATH, "w", encoding='utf-8') as f:
                        json.dump(fallos_existentes, f,
                                 indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ERROR CRÍTICO al guardar fallos.json: {e}")


def cargar_cuentas():
    with CUENTAS_LOCK:
        return cargar_json(CUENTAS_PATH)


def guardar_cuentas(cuentas):
    """Guarda los datos de cuentas.json usando el lock."""
    global CUENTAS_LOCK, CUENTAS_PATH
    with CUENTAS_LOCK:
        try:
            with open(CUENTAS_PATH, "w", encoding='utf-8') as f:
                json.dump(cuentas, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ERROR: No se pudieron guardar las cuentas: {e}")


def _update_account_state(nombre, new_state, razon=""):
    """Función interna para actualizar el estado de una cuenta y guardar."""
    with CUENTAS_LOCK:
        cuentas = cargar_cuentas()
        modificado = False
        for cuenta in cuentas:
            if cuenta.get("nombre") == nombre:
                cuenta["estado"] = new_state
                if new_state in ["alive"]:
                    if "quarantine_reason" in cuenta:
                        del cuenta["quarantine_reason"]
                    if "block_reason" in cuenta:
                        del cuenta["block_reason"]
                elif new_state == "cuarentena":
                    cuenta["quarantine_reason"] = razon
                elif new_state == "require_login":
                    cuenta["block_reason"] = razon

                modificado = True
                break
        if modificado:
            guardar_cuentas(cuentas)


def marcar_require_login(nombre, error_msg):
    """Marca una cuenta como require_login y la guarda (bloqueo por API de login)."""
    _update_account_state(nombre, "require_login", error_msg)


def marcar_cuarentena(nombre, error_msg):
    """Marca una cuenta como 'cuarentena' y la guarda (bloqueo por conexión/API general)."""
    _update_account_state(nombre, "cuarentena", error_msg)


# --- Funciones de Publicación (CRÍTICAS) ---


def publicar_texto(cuenta, post, post_index):
    """
    Retorna (exito:bool, error_detalle:str, action:str). 
    Action: 'success', 'quarantine', 'block', 'retry'
    """
    nombre = cuenta.get("nombre", "(sin nombre)")
    proxy = construir_proxies(cuenta["proxy"])

    try:
        cookies = cuenta["cookies"]
        cookie_header = construir_cookie_header(cookies)
        csrf_token = cookies["csrftoken"]
        caption = post["caption"]
        jazoest = calcular_jazoest(csrf_token)

        headers = {
            "x-instagram-ajax": "0", "x-csrftoken": csrf_token, "x-ig-app-id": "238260118697367",
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "cookie": cookie_header, "accept": "*/*",
        }

        payload = {
            "caption": caption, "publish_mode": "text_post",
            "text_post_app_info": json.dumps({"text_with_entities": {"entities": [], "text": caption}}),
            "upload_id": generar_upload_id(), "jazoest": jazoest,
        }

        res = requests.post(
            "https://www.threads.net/api/v1/media/configure_text_only_post/",
            headers=headers, data=payload, verify=False, proxies=proxy, timeout=30, allow_redirects=False
        )

        # Lógica de BLOQUEO por API (302)
        if res.status_code == 302:
            error_msg = f"BLOQUEO API: Require login (302). Revisar cookies."
            marcar_require_login(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "block"

        if res.ok:
            return True, "", "success"
        else:
            # Lógica de CUARENTENA por API (400, 403, etc.)
            error_msg = f"ERROR API (Texto): {res.status_code}. Respuesta: {res.text[:150]}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (API): Fallo {res.status_code}. Poniendo en cuarentena a {nombre}.")
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"

    # Cuarentena Inmediata para Errores Críticos de Conexión
    except requests.exceptions.ProxyError as e:
        error_msg = f"ERROR PROXY CAÍDO/MALO: {str(e)[:150]}"
        if "Max retries exceeded with url" in str(e):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (Proxy): Max Retries.")
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"

    except requests.exceptions.SSLError as e:
        error_msg = f"ERROR CONEXIÓN SSL: {str(e)[:150]}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (SSL): Falló SSL/TLS.")
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"

    except requests.exceptions.ConnectionError as e:
        error_msg = f"ERROR DE CONEXIÓN (General): {str(e)[:150]}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (Conexión): Fallo de conexión general.")
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"
        
    except Exception as e:
        error_msg = f"ERROR GENERAL: {str(e)[:150]}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"


def publicar_con_imagen(cuenta, post, post_index):
    nombre = cuenta.get("nombre", "(sin nombre)")
    cookies = cuenta["cookies"]
    proxy = construir_proxies(cuenta["proxy"])
    cookie_header = construir_cookie_header(cookies)
    csrf_token = cookies["csrftoken"]
    jazoest = calcular_jazoest(csrf_token)
    upload_id = generar_upload_id()

    image_path = os.path.join("grupos", cuenta["grupo"], post["img"]) 

    try:
        image_data = Path(image_path).read_bytes()
    except FileNotFoundError:
        error_msg = f"ERROR ARCHIVO: Imagen no encontrada en ruta: {image_path}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry" 

    # --- UPLOAD ---
    upload_url = f"https://www.threads.net/rupload_igphoto/fb_uploader_{upload_id}"
    upload_headers = {
        "x-instagram-ajax": "0", "x-csrftoken": csrf_token, "x-ig-app-id": "238260118697367",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "cookie": cookie_header, "content-type": "application/octet-stream",
        "accept": "*/*", "x-fb-waterfall-id": str(random.randint(1000000000, 9999999999)),
        "x-entity-type": "image", "x-entity-name": f"fb_uploader_{upload_id}",
        "x-entity-length": str(len(image_data)), "offset": "0", "x-threads-request-id": str(random.randint(1000000000, 9999999999))
    }

    try:
        requests.post(upload_url, headers=upload_headers,
                      data=image_data, verify=False, proxies=proxy, timeout=30)
    # Cuarentena Inmediata para Errores Críticos de Conexión (Upload)
    except requests.exceptions.ProxyError as e:
        error_msg = f"ERROR PROXY CAÍDO/MALO (Upload): {str(e)[:150]}"
        if "Max retries exceeded with url" in str(e):
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"
    except requests.exceptions.SSLError as e:
        error_msg = f"ERROR CONEXIÓN SSL (Upload): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"
    except requests.exceptions.ConnectionError as e:
        error_msg = f"ERROR DE CONEXIÓN (General - Upload): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"
    except Exception as e:
        error_msg = f"ERROR GENERAL (Upload): {str(e)[:150]}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"

    # --- CONFIGURE ---
    configure_url = "https://www.threads.net/api/v1/media/configure_text_post_app_feed/"
    caption = post["caption"]
    configure_payload = {
        "caption": caption, "upload_id": upload_id, "text_post_app_info": json.dumps({"text_with_entities": {"entities": [], "text": caption}}),
        "jazoest": jazoest, "session_id": upload_id, 
    }
    
    # CORRECCIÓN: Definir configure_headers como copia de upload_headers y Content-Type
    configure_headers = upload_headers.copy()
    configure_headers["content-type"] = "application/x-www-form-urlencoded;charset=UTF-8"

    try:
        res_config = requests.post(configure_url, headers=configure_headers,
                                   data=configure_payload, verify=False, proxies=proxy)

        # Lógica de BLOQUEO por API (302)
        if res_config.status_code == 302:
            error_msg = f"BLOQUEO API: Require login (302). Revisar cookies."
            marcar_require_login(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "block"

        if res_config.ok:
            return True, "", "success"
        else:
            # Lógica de CUARENTENA por API (400, 403, etc.)
            error_msg = f"ERROR API (Configure Imagen): {res_config.status_code}. Respuesta: {res_config.text[:150]}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (API): Fallo {res_config.status_code}. Poniendo en cuarentena a {nombre}.")
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"
    
    # Cuarentena Inmediata para Errores Críticos de Conexión (Configure)
    except requests.exceptions.ProxyError as e:
        error_msg = f"ERROR PROXY CAÍDO/MALO (Configure): {str(e)[:150]}"
        if "Max retries exceeded with url" in str(e):
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"
    except requests.exceptions.SSLError as e:
        error_msg = f"ERROR CONEXIÓN SSL (Configure): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"
    except requests.exceptions.ConnectionError as e:
        error_msg = f"ERROR DE CONEXIÓN (General - Configure): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"
    except Exception as e:
        error_msg = f"ERROR GENERAL (Configure): {str(e)[:150]}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"


def publicar_carrusel(cuenta, post, post_index):
    nombre = cuenta.get("nombre", "(sin nombre)")
    cookies = cuenta["cookies"]
    proxy = construir_proxies(cuenta["proxy"])
    cookie_header = construir_cookie_header(cookies)
    csrf_token = cookies["csrftoken"]
    jazoest = calcular_jazoest(csrf_token)
    upload_ids = []
    
    upload_headers = {} 

    try:
        # 1. Upload todas las imágenes
        for img_name in post["imgs"]:
            upload_id = generar_upload_id()
            
            image_path = os.path.join("grupos", cuenta["grupo"], img_name) 
            image_data = Path(image_path).read_bytes()

            upload_url = f"https://www.threads.net/rupload_igphoto/fb_uploader_{upload_id}"
            upload_headers = {
                "x-instagram-ajax": "0", "x-csrftoken": csrf_token, "x-ig-app-id": "238260118697367",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                "cookie": cookie_header, "content-type": "application/octet-stream",
                "accept": "*/*", "x-fb-waterfall-id": str(random.randint(1000000000, 9999999999)),
                "x-entity-type": "image", "x-entity-name": f"fb_uploader_{upload_id}",
                "x-entity-length": str(len(image_data)), "offset": "0", "x-threads-request-id": str(random.randint(1000000000, 9999999999))
            }

            try:
                requests.post(upload_url, headers=upload_headers,
                              data=image_data, verify=False, proxies=proxy, timeout=30)
                upload_ids.append(upload_id)
            # Cuarentena Inmediata para Errores Críticos de Conexión (Upload Carrusel)
            except requests.exceptions.ProxyError as e:
                error_msg = f"ERROR PROXY CAÍDO/MALO (Upload Carrusel): {str(e)[:150]}"
                if "Max retries exceeded with url" in str(e):
                    marcar_cuarentena(nombre, error_msg)
                    agregar_fallo_en_memoria(nombre, post_index, error_msg)
                    return False, error_msg, "quarantine"
                agregar_fallo_en_memoria(nombre, post_index, error_msg)
                return False, error_msg, "retry"
            except requests.exceptions.SSLError as e:
                error_msg = f"ERROR CONEXIÓN SSL (Upload Carrusel): {str(e)[:150]}"
                marcar_cuarentena(nombre, error_msg)
                agregar_fallo_en_memoria(nombre, post_index, error_msg)
                return False, error_msg, "quarantine"
            except requests.exceptions.ConnectionError as e:
                error_msg = f"ERROR DE CONEXIÓN (General - Upload Carrusel): {str(e)[:150]}"
                marcar_cuarentena(nombre, error_msg)
                agregar_fallo_en_memoria(nombre, post_index, error_msg)
                return False, error_msg, "quarantine"
            except Exception as e:
                error_msg = f"ERROR GENERAL (Upload Carrusel): {str(e)[:150]}"
                agregar_fallo_en_memoria(nombre, post_index, error_msg)
                return False, error_msg, "retry"
                
        # 2. Configure Sidecar
        if not upload_ids:
            return False, "ERROR CRÍTICO: No se subió ninguna imagen para el carrusel.", "retry"
            
        configure_url = "https://www.threads.net/api/v1/media/configure_sidecar/"
        caption = post["caption"]

        children_metadata = [
            {"upload_id": uid, "text_post_app_info": {
                "text_with_entities": {"entities": [], "text": caption}}}
            for uid in upload_ids
        ]

        payload_data = {
            "caption": caption, "client_sidecar_id": generar_upload_id(), "children_metadata": children_metadata,
            "text_post_app_info": json.dumps({"text_with_entities": {"entities": [], "text": caption}}),
            "jazoest": jazoest,
        }
        
        configure_headers = upload_headers.copy() 
        configure_headers["content-type"] = "application/json;charset=UTF-8" # Content-Type JSON

        res = requests.post(configure_url, headers=configure_headers, data=json.dumps(
            payload_data), verify=False, proxies=proxy, timeout=30)

        # Lógica de BLOQUEO por API (302)
        if res.status_code == 302:
            error_msg = f"BLOQUEO API: Require login (302). Revisar cookies."
            marcar_require_login(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "block"

        if res.ok:
            return True, "", "success"
        else:
            # Lógica de CUARENTENA por API (400, 403, etc.)
            error_msg = f"ERROR API (Configure Carrusel): {res.status_code}. Respuesta: {res.text[:150]}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (API): Fallo {res.status_code}. Poniendo en cuarentena a {nombre}.")
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"

    # Cuarentena Inmediata para Errores Críticos de Conexión (Configure Carrusel)
    except requests.exceptions.ProxyError as e:
        error_msg = f"ERROR PROXY CAÍDO/MALO (Carrusel): {str(e)[:150]}"
        if "Max retries exceeded with url" in str(e):
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"
    except requests.exceptions.SSLError as e:
        error_msg = f"ERROR CONEXIÓN SSL: {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"
    except requests.exceptions.ConnectionError as e:
        error_msg = f"ERROR DE CONEXIÓN (General - Carrusel): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "quarantine"
    except FileNotFoundError:
        error_msg = "ERROR ARCHIVO: Una o más imágenes del carrusel no fueron encontradas."
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"
    except Exception as e:
        error_msg = f"ERROR GENERAL (Carrusel): {str(e)[:150]}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"


def get_human_delay_cycle(grupo_nombre):
    """Generador que calcula el delay humanizado en minutos."""
    # 🟢 Se usa get_post_delay para obtener el delay base (Global o Individual)
    
    # ⚠️ Nota: Esta función generadora ya no se usa directamente en procesar_cuenta
    # como antes. El cálculo de delay se hace ahora por post dentro del ciclo.
    
    # Si quieres usar un generador con el delay global
    min_min = DELAY_CONFIG['min_minutes']
    max_min = DELAY_CONFIG['max_minutes']
    jitter = DELAY_CONFIG['jitter']

    while True:
        delay_base = random.randint(min_min, max_min)
        delay_jitter = random.randint(-jitter, jitter)
        final_delay = max(1, delay_base + delay_jitter)
        yield final_delay

# --- LÓGICA PRINCIPAL ---


def procesar_cuenta(cuenta):
    """Función que gestiona la publicación de una sola cuenta en un hilo con ciclo de delay."""
    if not get_running_status():
        return

    nombre_cuenta = cuenta.get("nombre", "Desconocida")
    grupo_nombre = cuenta.get("grupo", "default")

    grupo_path = os.path.join("grupos", f"{grupo_nombre}.json")
    all_posts = cargar_json(grupo_path)

    if not all_posts:
        print(
            f"⚠️ Grupo '{grupo_nombre}' de la cuenta {nombre_cuenta} no encontrado o vacío en la ruta: {grupo_path}")
        return

    pending_posts = list(all_posts)
    
    # Se elimina el generador, el delay se calcula por post.
    # delay_cycle = get_human_delay_cycle(grupo_nombre) 

    try:
        while get_running_status(): 
            if not pending_posts:
                print(
                    f"\n🔄 Grupo {grupo_nombre} de {nombre_cuenta} completó un ciclo. Reiniciando la lista de posts.")
                pending_posts = list(all_posts)
                if not pending_posts:
                    print(
                        f"⚠️ La lista de posts sigue vacía. Deteniendo {nombre_cuenta}.")
                    break

            current_post = pending_posts.pop(0)

            try:
                original_index = all_posts.index(current_post)
            except ValueError:
                original_index = -1

            print(
                f"\n➡️ Cuenta: {nombre_cuenta} - Publicando post ID original #{original_index + 1}...")

            exito = False
            error_detalle = "Error desconocido."
            action = "retry"

            try:
                # --- Lógica de Determinación de Tipo de Post ---
                post_img_val = current_post.get("img", "").strip()
                imagenes = [img.strip() for img in post_img_val.split(
                    "|") if img.strip()] if post_img_val else []

                if len(imagenes) > 1:
                    current_post["imgs"] = imagenes
                    exito, error_detalle, action = publicar_carrusel(
                        cuenta, current_post, original_index)
                elif len(imagenes) == 1:
                    current_post["img"] = imagenes[0]
                    exito, error_detalle, action = publicar_con_imagen(
                        cuenta, current_post, original_index)
                else:
                    exito, error_detalle, action = publicar_texto(
                        cuenta, current_post, original_index)

            except Exception as e:
                error_msg = str(e)
                print(
                    f"⚠️ Excepción general al intentar publicar: {error_msg}")
                exito = False
                error_detalle = f"Excepción crítica en el hilo: {error_msg[:150]}"
                action = "retry"

            # 2. Lógica de Quarantena/Bloqueo y Reintento

            if action == "quarantine":
                print(
                    f"🛑 Cuenta ({nombre_cuenta}) 🚨 ¡PROXY/API CRÍTICA! Razón: {error_detalle}. Se ha colocado en **CUARENTENA** y se detiene el hilo.")
                return 

            if action == "block":
                print(
                    f"🛑 Cuenta ({nombre_cuenta}) 🚨 ¡REQUIERE LOGIN/BLOQUEO API! Razón: {error_detalle}. Se detiene el hilo.")
                return 

            if not exito:
                # Si falla (action="retry" o error general), se devuelve a la cola y se aplica un delay
                print(
                    f"❌ Falló la publicación del post ID {original_index+1}.")
                print(f"⚠️ Razón del fallo: {error_detalle}")
                print(f"🔄 Se reintentará al final de la cola.")
                pending_posts.append(current_post)

                # Delay de recuperación corto 
                delay_minutes_total = random.randint(11, 21)
                print(
                    f"⏳ Cuenta ({nombre_cuenta}) ❌ Post fallido. Aplicando delay de recuperación: {delay_minutes_total} minutos.")
            else:
                # Si tiene éxito (action="success")
                # 🟢 El delay se calcula aquí usando la lógica de prioridad (Individual, Global)
                delay_minutes_total = get_post_delay(current_post, grupo_nombre)
                delay_hours_display = delay_minutes_total / 60

                print(
                    f"⏳ Cuenta ({nombre_cuenta}) ✅ Post exitoso. Aplicando delay del ciclo: {delay_hours_display:.2f} horas ({delay_minutes_total} min).")

            # 3. Espera Controlada
            sleep_seconds = delay_minutes_total * 12
            
            if not interruptible_sleep(sleep_seconds):
                print(f"Cuenta ({nombre_cuenta}) detenido por interfaz.")
                return


        print(
            f"✅ Hilo de cuenta ({nombre_cuenta}) terminado por orden de la GUI.")

    except Exception as e:
        print(f"❌ Error general en cuenta ({nombre_cuenta}): {str(e)}")
        agregar_fallo_en_memoria(
            nombre_cuenta, -1, f"Error hilo principal: {str(e)}")


def run_posting_threads():
    if not get_running_status(): 
        return

    print("🚀 Iniciando ejecución principal...")
    cuentas = cargar_cuentas()

    if not cuentas:
        print("⚠️ No se encontraron cuentas en cuentas.json. Deteniendo.")
        set_running_status(False)
        return

    hilo_fallos = threading.Thread(
        target=guardar_fallos_periodicamente, daemon=True)
    hilo_fallos.start()

    hilos = []

    for cuenta in cuentas:
        nombre = cuenta.get('nombre', 'Desconocida')
        is_enabled = cuenta.get("enabled", True)
        is_active = cuenta.get("estado", "alive") == "alive"

        # CORRECCIÓN CLAVE: Iniciar hilo directamente si está activo, omitiendo la verificación inicial estricta.
        if is_enabled and is_active:
            hilo = threading.Thread(
                target=procesar_cuenta, args=(cuenta,), daemon=True)
            hilo.start()
            hilos.append(hilo)

            # --- DELAY ENTRE EL INICIO DE HILOS (HUMANIZACIÓN) ---
            delay_start = random.randint(13, 47)  # Delay en segundos
            print(
                f"😴 Esperando {delay_start} segundos antes de iniciar el hilo de la próxima cuenta...")
            
            if not interruptible_sleep(delay_start):
                 print("⚠️ Proceso de inicio de hilos interrumpido.")
                 break
            # ----------------------------------------------------
        else:
            estado_str = cuenta.get('estado', 'alive')
            enabled_str = 'ACTIVADA' if is_enabled else 'DESACTIVADA'
            print(
                f"⏩ Saltando cuenta {nombre}: 'Usar'={enabled_str}, estado={estado_str}")

    while get_running_status() and any(hilo.is_alive() for hilo in hilos):
        time.sleep(1)

    print("✅ Hilos de publicación detenidos.")
    set_running_status(False)
    
    global FALLOS_EN_MEMORIA, FALLOS_LOCK, FALLOS_PATH
    
    if FALLOS_EN_MEMORIA:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 💾 Guardando {len(FALLOS_EN_MEMORIA)} fallos finales...")
        with FALLOS_LOCK:
            fallos_existentes = []
            if os.path.exists(FALLOS_PATH):
                 try:
                    with open(FALLOS_PATH, "r", encoding='utf-8') as f:
                        fallos_existentes = json.load(f)
                 except: 
                     pass
            
            fallos_existentes.extend(FALLOS_EN_MEMORIA)
            FALLOS_EN_MEMORIA.clear()
            
            try:
                with open(FALLOS_PATH, "w", encoding='utf-8') as f:
                    json.dump(fallos_existentes, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ERROR CRÍTICO al guardar fallos al detener el bot: {e}")
                
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Hilos de publicación detenidos.")