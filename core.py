# core_poster.py
import shutil
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
from PIL import Image
import io

# Suprime advertencias de SSL/InsecureRequestWarning (útil con proxies)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Control de Ejecución para la GUI ---
IS_RUNNING = False
DELAY_CONFIG = {  # CONFIGURACIÓN GLOBAL DE DELAY
    "min_minutes": 13,
    "max_minutes": 29,  
    "jitter": 7, # Jitter por defecto (variación aleatoria)
    "use_individual_delays": True  # True: usa delays individuales, False: usa delay general
}

# --- Variables Globales y Utilerías ---
CUENTAS_PATH = "cuentas.json"
FALLOS_PATH = "fallos.json"

# --- Control de Fallos Globales y Thread-Safe ---
FALLOS_EN_MEMORIA = []
FALLOS_LOCK = threading.Lock() # Lock para acceso thread-safe a FALLOS_EN_MEMORIA
CUENTAS_LOCK = threading.Lock() # Lock para acceso thread-safe a cuentas.json

# --- Funciones Básicas y Configuración ---

def set_running_status(status):
    """Establece la bandera global de estado."""
    global IS_RUNNING
    IS_RUNNING = status
    
def get_running_status():
    """Retorna el estado actual de la bandera IS_RUNNING."""
    return IS_RUNNING

def update_delay_config(min_min, max_min, use_individual_delays=None):
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
    
    if use_individual_delays is not None:
        DELAY_CONFIG["use_individual_delays"] = use_individual_delays

    mode = "individuales" if DELAY_CONFIG["use_individual_delays"] else "general"
    print(f"⚙️ Configuración de delay actualizada: {DELAY_CONFIG['min_minutes']}-{DELAY_CONFIG['max_minutes']} min | Modo: {mode}")

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

# --- Inicialización de Archivos ---
if not os.path.exists(FALLOS_PATH):
    with open(FALLOS_PATH, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

if not os.path.exists(CUENTAS_PATH):
    with open(CUENTAS_PATH, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

# --- Funciones de Utilidad ---

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
    return f"2{sum(ord(c) for c in csrf_token)}"

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
        print(f"❌ Error de formato en proxy: {proxy_str}. Debe ser user:pass@host:port.")
        return None

# --- Gestión de Fallos y Cuentas ---

def agregar_fallo_en_memoria(nombre_cuenta, post_index, error_msg):
    """Añade un fallo a la lista global en memoria de forma thread-safe."""
    with FALLOS_LOCK:
        FALLOS_EN_MEMORIA.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nombre": nombre_cuenta,
            "post": post_index,
            "error_msg": error_msg
        })

def guardar_fallos_periodicamente():
    """Hilo para guardar los fallos en disco de forma segura."""
    while get_running_status(): 
        if not interruptible_sleep(180): # Espera 3 minutos de forma interrumpible
            break 
            
        with FALLOS_LOCK:
            if FALLOS_EN_MEMORIA:
                fallos_existentes = [] 
                
                if os.path.exists(FALLOS_PATH):
                    try:
                        with open(FALLOS_PATH, "r", encoding='utf-8') as f:
                            fallos_existentes = json.load(f)
                    except json.JSONDecodeError:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Advertencia: fallos.json corrupto.")
                    except Exception as e:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ERROR desconocido al cargar fallos.json: {e}")

                fallos_existentes.extend(FALLOS_EN_MEMORIA)
                FALLOS_EN_MEMORIA.clear()

                try:
                    with open(FALLOS_PATH, "w", encoding='utf-8') as f:
                        json.dump(fallos_existentes, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ERROR CRÍTICO al guardar fallos.json: {e}")

def cargar_cuentas():
    """Carga datos de cuentas.json de forma segura."""
    with CUENTAS_LOCK:
        return cargar_json(CUENTAS_PATH)

def guardar_cuentas(cuentas):
    """Guarda los datos de cuentas.json usando el lock."""
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

# --- Verificación de Cuentas ---

def verificar_estado_cuenta(cuenta):
    """Verifica si las cookies de una cuenta son válidas"""
    nombre = cuenta.get("nombre", "(sin nombre)")
    cookies = cuenta["cookies"]
    proxy = construir_proxies(cuenta["proxy"])
    cookie_header = construir_cookie_header(cookies)
    
    headers = {
        "authority": "www.threads.net",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "cookie": cookie_header,
        "sec-ch-ua": '"Not/A)Brand";v="99", "Google Chrome";v="115", "Chromium";v="115"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(
            "https://www.threads.net/",
            headers=headers,
            proxies=proxy,
            verify=False,
            timeout=30,
            allow_redirects=False
        )
        
        if response.status_code == 200 and "threads.net" in response.url:
            print(f"✅ Cuenta {nombre}: Cookies VÁLIDAS")
            return True
        elif response.status_code == 302:
            print(f"❌ Cuenta {nombre}: Cookies EXPIRADAS (redirect to login)")
            return False
        else:
            print(f"⚠️ Cuenta {nombre}: Estado incierto - {response.status_code}")
            return False
            
    except Exception as e:
        print(f"🚨 Cuenta {nombre}: Error de conexión - {str(e)}")
        return False

# --- Funciones de Publicación ---

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
            # FIX: Lógica de CUARENTENA por API (400, 403, etc.)
            error_msg = f"ERROR API (Texto): {res.status_code}. Respuesta: {res.text[:150]}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (API): Fallo {res.status_code}. Poniendo en cuarentena a {nombre}.")
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"

    # FIX: Cuarentena Inmediata para Errores Críticos de Conexión
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

def verificar_y_corregir_ruta_imagen(image_path, grupo_nombre):
    """
    Verifica y corrige la ruta de la imagen, buscando en diferentes ubicaciones posibles.
    """
    # Si ya es una ruta absoluta y existe
    if os.path.isabs(image_path) and os.path.exists(image_path):
        return image_path
    
    # Si es una ruta relativa, probar diferentes ubicaciones
    posibles_rutas = [
        image_path,  # Ruta original
        os.path.join("grupos", grupo_nombre, image_path),  # Dentro de la carpeta del grupo
        os.path.join("grupos", grupo_nombre, "imagenes", image_path),  # En subcarpeta imagenes
        os.path.join(grupo_nombre, image_path),  # En carpeta del grupo en raíz
    ]
    
    for ruta in posibles_rutas:
        if os.path.exists(ruta):
            return ruta
    
    # Si no se encuentra, devolver la ruta original para mostrar el error
    return image_path

def publicar_con_imagen(cuenta, post, post_index):
    nombre = cuenta.get("nombre", "(sin nombre)")
    cookies = cuenta["cookies"]
    proxy = construir_proxies(cuenta["proxy"])
    cookie_header = construir_cookie_header(cookies)
    csrf_token = cookies["csrftoken"]
    jazoest = calcular_jazoest(csrf_token)
    upload_id = generar_upload_id()
    grupo_nombre = cuenta.get("grupo", "default")

    # Encontrar la imagen
    image_path_original = post["img"]
    image_path = verificar_y_corregir_ruta_imagen(image_path_original, grupo_nombre)
    
    if not os.path.exists(image_path):
        error_msg = f"ERROR ARCHIVO NO ENCONTRADO: {image_path_original}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"

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
    # FIX: Cuarentena Inmediata para Errores Críticos de Conexión (Upload)
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
    
    # 🟢 CORRECCIÓN: Definir configure_headers como copia de upload_headers
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
            # FIX: Lógica de CUARENTENA por API (400, 403, etc.)
            error_msg = f"ERROR API (Configure Imagen): {res_config.status_code}. Respuesta: {res_config.text[:150]}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (API): Fallo {res_config.status_code}. Poniendo en cuarentena a {nombre}.")
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"
    
    # FIX: Cuarentena Inmediata para Errores Críticos de Conexión (Configure)
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
    
    # Inicializar upload_headers fuera del bucle para asegurar el ámbito
    upload_headers = {} # Se llenará con el último conjunto de headers del bucle

    try:
        # 1. Upload todas las imágenes
        for img_name in post["imgs"]:
            upload_id = generar_upload_id()
            
            # FIX: Corregir ruta de imagen para buscar dentro de la carpeta del grupo
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
            # FIX: Cuarentena Inmediata para Errores Críticos de Conexión (Upload Carrusel)
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
            # Si no se subió ninguna imagen (por error de archivo), fallar
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
        
        # 🟢 CORRECCIÓN: Definir configure_headers como copia de upload_headers y actualizar Content-Type
        configure_headers = upload_headers.copy() 
        configure_headers["content-type"] = "application/json;charset=UTF-8" # Para sidecar, el content-type es JSON

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
            # FIX: Lógica de CUARENTENA por API (400, 403, etc.)
            error_msg = f"ERROR API (Configure Carrusel): {res.status_code}. Respuesta: {res.text[:150]}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (API): Fallo {res.status_code}. Poniendo en cuarentena a {nombre}.")
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "quarantine"

    # FIX: Cuarentena Inmediata para Errores Críticos de Conexión (Configure Carrusel)
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

# --- Lógica de Delays ---

def get_post_delay(post, grupo_nombre):
    """
    Determina el delay para un post basado en la configuración.
    Prioridad: Delay individual > Delay grupal > Delay global
    """
    # Si está habilitado el uso de delays individuales y el post tiene delays específicos
    if DELAY_CONFIG["use_individual_delays"] and post.get('delay_min') and post.get('delay_max'):
        delay_min = int(post.get('delay_min', 13))
        delay_max = int(post.get('delay_max', 29))
        
        # Aplicar jitter a delays individuales
        jitter = DELAY_CONFIG["jitter"]
        delay_base = random.randint(delay_min, delay_max)
        delay_jitter = random.randint(-jitter, jitter)
        final_delay = max(1, delay_base + delay_jitter)
        
        print(f"⏱️ Delay individual: {delay_min}-{delay_max} min + jitter {jitter} = {final_delay} min")
        return final_delay
    
    # Si no hay delays individuales o están deshabilitados, usar delay grupal o global
    delay_min = DELAY_CONFIG["min_minutes"]
    delay_max = DELAY_CONFIG["max_minutes"]
    jitter = DELAY_CONFIG["jitter"]
    
    delay_base = random.randint(delay_min, delay_max)
    delay_jitter = random.randint(-jitter, jitter)
    final_delay = max(1, delay_base + delay_jitter)
    
    source = "general" if not DELAY_CONFIG["use_individual_delays"] else "global (sin delays individuales)"
    print(f"⏱️ Delay {source}: {delay_min}-{delay_max} min + jitter {jitter} = {final_delay} min")
    return final_delay

# --- Función Principal de Publicación ---

def publicar_cuenta(cuenta, posts, callback_progreso=None):
    """
    Función principal que publica una secuencia de posts para una cuenta.
    Retorna un diccionario con el resumen de la ejecución.
    """
    nombre = cuenta.get("nombre", "(sin nombre)")
    grupo_nombre = cuenta.get("grupo", "default")
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 👤 Iniciando publicación para cuenta: {nombre}")

    # Verificar cookies antes de publicar
    if not verificar_estado_cuenta(cuenta):
        error_msg = "Cookies inválidas o expiradas"
        marcar_require_login(nombre, error_msg)
        return {
            "cuenta": nombre,
            "estado": "error",
            "error": error_msg,
            "posts_publicados": 0,
            "total_posts": len(posts)
        }

    posts_publicados = 0
    posts_fallados = 0
    posts_omitidos = 0

    for i, post in enumerate(posts):
        if not get_running_status():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Detención solicitada. Interrumpiendo publicación de {nombre}.")
            break

        # Verificar si el post está activo
        if not post.get("activo", True):
            print(f"⏭️ Post {i+1} inactivo. Omitiendo...")
            posts_omitidos += 1
            continue

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 📝 Publicando post {i+1}/{len(posts)} para {nombre}")

        # Determinar tipo de post y llamar a la función correspondiente
        if "imgs" in post and len(post["imgs"]) > 1:
            # Carrusel
            exito, error_detalle, action = publicar_carrusel(cuenta, post, i+1)
        elif "img" in post and post["img"]:
            # Imagen única
            exito, error_detalle, action = publicar_con_imagen(cuenta, post, i+1)
        else:
            # Texto
            exito, error_detalle, action = publicar_texto(cuenta, post, i+1)

        if exito:
            print(f"✅ Post {i+1} publicado exitosamente")
            posts_publicados += 1
        else:
            print(f"❌ Falló el post {i+1}: {error_detalle}")
            posts_fallados += 1

            # Manejar acciones especiales
            if action == "block":
                print(f"🚫 Cuenta {nombre} bloqueada. Deteniendo publicación.")
                break
            elif action == "quarantine":
                print(f"🚫 Cuenta {nombre} en cuarentena. Deteniendo publicación.")
                break
            elif action == "retry":
                print(f"🔄 Reintentando post {i+1}...")
                # Reintento simple
                time.sleep(5)
                exito, error_detalle, action = publicar_texto(cuenta, post, i+1) if "img" not in post else publicar_con_imagen(cuenta, post, i+1)
                if exito:
                    print(f"✅ Post {i+1} publicado en reintento")
                    posts_publicados += 1
                    posts_fallados -= 1
                else:
                    print(f"❌ Falló el reintento del post {i+1}")

        # Actualizar progreso en la GUI
        if callback_progreso:
            callback_progreso(nombre, i+1, len(posts), posts_publicados, posts_fallados)

        # Delay entre posts (excepto después del último)
        if i < len(posts) - 1 and get_running_status():
            delay_minutos = get_post_delay(post, grupo_nombre)
            print(f"⏳ Esperando {delay_minutos} minutos antes del siguiente post...")
            
            if not interruptible_sleep(delay_minutos * 60):
                break

    # Resumen final
    estado = "completado" if posts_publicados == len(posts) else "interrumpido" if not get_running_status() else "con_fallos"
    
    resumen = {
        "cuenta": nombre,
        "estado": estado,
        "posts_publicados": posts_publicados,
        "posts_fallados": posts_fallados,
        "posts_omitidos": posts_omitidos,
        "total_posts": len(posts)
    }
    
    print(f"\n📊 Resumen {nombre}: {posts_publicados}/{len(posts)} posts publicados")
    return resumen

# --- Función Principal del Bot ---

def iniciar_bot(callback_progreso=None, callback_fin_cuenta=None):
    """
    Función principal del bot que gestiona la publicación para todas las cuentas.
    """
    global IS_RUNNING
    IS_RUNNING = True
    
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🤖 Iniciando bot de publicación...")
    
    # Iniciar hilo para guardar fallos periódicamente
    hilo_fallos = threading.Thread(target=guardar_fallos_periodicamente, daemon=True)
    hilo_fallos.start()

    # Cargar cuentas
    cuentas = cargar_cuentas()
    if not cuentas:
        print("❌ No hay cuentas configuradas.")
        IS_RUNNING = False
        return

    # Filtrar solo cuentas activas
    cuentas_activas = [c for c in cuentas if c.get("estado") == "alive"]
    if not cuentas_activas:
        print("❌ No hay cuentas activas para publicar.")
        IS_RUNNING = False
        return

    print(f"👥 Cuentas activas encontradas: {len(cuentas_activas)}")

    resultados = []
    
    # Procesar cada cuenta
    for cuenta in cuentas_activas:
        if not get_running_status():
            break
            
        nombre = cuenta.get("nombre", "(sin nombre)")
        grupo = cuenta.get("grupo", "default")
        
        print(f"\n🎯 Procesando cuenta: {nombre} (grupo: {grupo})")
        
        # Cargar posts del grupo
        grupo_path = os.path.join("grupos", grupo, "posts.json")
        if not os.path.exists(grupo_path):
            print(f"❌ No se encontró posts.json para el grupo {grupo}")
            continue
            
        posts = cargar_json(grupo_path)
        if not posts:
            print(f"❌ No hay posts para publicar en el grupo {grupo}")
            continue
            
        print(f"📄 Posts a publicar: {len(posts)}")
        
        # Publicar para esta cuenta
        resultado = publicar_cuenta(cuenta, posts, callback_progreso)
        resultados.append(resultado)
        
        # Notificar fin de cuenta
        if callback_fin_cuenta:
            callback_fin_cuenta(resultado)
            
        # Delay entre cuentas (si no es la última)
        if cuenta != cuentas_activas[-1] and get_running_status():
            delay_cuentas = random.randint(2, 5)  # Delay corto entre cuentas
            print(f"⏳ Esperando {delay_cuentas} minutos antes de la siguiente cuenta...")
            if not interruptible_sleep(delay_cuentas * 60):
                break

    # Resumen final
    print(f"\n📊 RESUMEN FINAL:")
    total_publicados = sum(r["posts_publicados"] for r in resultados)
    total_fallados = sum(r["posts_fallados"] for r in resultados)
    total_cuentas = len(resultados)
    
    print(f"✅ Cuentas procesadas: {total_cuentas}")
    print(f"✅ Posts publicados: {total_publicados}")
    print(f"❌ Posts fallados: {total_fallados}")
    
    IS_RUNNING = False
    return resultados

def detener_bot():
    """Detiene la ejecución del bot de forma segura."""
    global IS_RUNNING
    IS_RUNNING = False
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🛑 Señal de detención enviada al bot...")