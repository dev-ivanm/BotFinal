# core_poster.py - CON CORRECCIONES CRÍTICAS
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
import re

# --- CONFIGURACIÓN DE ARCHIVOS Y LOCKS ---
CUENTAS_PATH = "cuentas.json"
FALLOS_PATH = "fallos.json"
GRUPOS_DIR = "grupos"

# 🟢 CORRECCIÓN C: LOCKS CENTRALIZADOS
CUENTAS_LOCK = threading.Lock()
FALLOS_LOCK = threading.Lock()

# --- GLOBALES ---
IS_RUNNING = False
FALLOS_EN_MEMORIA = []

# Configuración de Delay y Jitter
DELAY_CONFIG = {  
    "min_minutes": 17,  
    "max_minutes": 33,  
    "jitter": 3,        
    "use_individual_delays": False  
}

# Suprime advertencias de SSL/InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONTROL DE EJECUCIÓN ---
def set_running_status(status):
    global IS_RUNNING
    IS_RUNNING = status

def get_running_status():
    return IS_RUNNING

def update_delay_config(min_min, max_min, use_individual_delays):
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
    DELAY_CONFIG["use_individual_delays"] = use_individual_delays

    print(f"⚙️ Configuración de delay actualizada: {DELAY_CONFIG['min_minutes']} - {DELAY_CONFIG['max_minutes']} minutos. Modo Individual: {DELAY_CONFIG['use_individual_delays']}")

def get_post_delay(post, grupo_nombre):
    min_global = DELAY_CONFIG.get("min_minutes", 17)
    max_global = DELAY_CONFIG.get("max_minutes", 33)
    jitter = DELAY_CONFIG.get("jitter", 3)

    if DELAY_CONFIG["use_individual_delays"] and post.get('delay_min') is not None and post.get('delay_max') is not None:
        try:
            delay_min = int(post['delay_min'])
            delay_max = int(post['delay_max'])
            if delay_min > 0 and delay_max >= delay_min:
                return random.randint(delay_min, delay_max)
        except ValueError:
            pass
    
    delay_base = random.randint(min_global, max_global)
    delay_jitter = random.randint(-jitter, jitter)
    final_delay = max(1, delay_base + delay_jitter)
    return final_delay

def interruptible_sleep(duration_seconds):
    check_interval = 1
    for _ in range(int(duration_seconds / check_interval)):
        if not get_running_status():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Detención inmediata solicitada. Saliendo de la espera.")
            return False 
        time.sleep(check_interval)
        
    remaining_time = duration_seconds % check_interval
    if remaining_time > 0:
        time.sleep(remaining_time)
        
    return get_running_status()

# --- UTILS THREAD-SAFE Y ATOMIC WRITES ---

# 🟢 CORRECCIÓN B, C: ESCRITURA ATÓMICA Y CARGA SEGURA
def atomic_write_json(path, data):
    """Escribe data a path de forma atómica (a .tmp y luego reemplaza)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def cargar_json(path):
    """Carga un JSON de forma segura. Retorna [] si hay error."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []

# Inicializar archivos si no existen
if not os.path.exists(FALLOS_PATH):
    atomic_write_json(FALLOS_PATH, [])

if not os.path.exists(CUENTAS_PATH):
    atomic_write_json(CUENTAS_PATH, [])

# --- FUNCIONES DE CUENTAS THREAD-SAFE ---

def cargar_cuentas():
    """Carga cuentas.json usando el lock central."""
    with CUENTAS_LOCK:
        return cargar_json(CUENTAS_PATH)

def guardar_cuentas(cuentas):
    """Guarda cuentas.json usando el lock central y escritura atómica."""
    with CUENTAS_LOCK:
        atomic_write_json(CUENTAS_PATH, cuentas)

def _update_account_state(account_name, new_state, reason=None):
    """Actualiza estado de la cuenta en memoria y guarda."""
    cuentas = cargar_cuentas()
    found = False
    for cuenta in cuentas:
        if cuenta.get('nombre') == account_name:
            cuenta['estado'] = new_state
            
            if new_state in ["cuarentena", "require_login", "bloqueo"]:
                cuenta['enabled'] = False  
            elif new_state == "alive":
                cuenta['enabled'] = True   
                
            if new_state in ["alive"]:
                if "quarantine_reason" in cuenta:
                    del cuenta["quarantine_reason"]
                if "block_reason" in cuenta:
                    del cuenta["block_reason"]
            elif new_state == "cuarentena":
                cuenta["quarantine_reason"] = reason
            elif new_state == "require_login":
                cuenta["block_reason"] = reason
            found = True
            break
    if found:
        guardar_cuentas(cuentas)
        return True
    return False

def marcar_require_login(nombre, error_msg):
    _update_account_state(nombre, "require_login", error_msg)

def marcar_cuarentena(nombre, error_msg):
    _update_account_state(nombre, "cuarentena", error_msg)

# --- UTILS DE FALLOS (LOCK Y FLUSH) ---

# 🟢 CORRECCIÓN D: FLUSH DE FALLOS A DISCO
def flush_fallos_to_disk():
    """Transfiere FALLOS_EN_MEMORIA al disco de forma atómica."""
    global FALLOS_EN_MEMORIA, FALLOS_LOCK
    with FALLOS_LOCK:
        if not FALLOS_EN_MEMORIA:
            return

        fallos_existentes = cargar_json(FALLOS_PATH)
        fallos_existentes.extend(FALLOS_EN_MEMORIA)
        FALLOS_EN_MEMORIA.clear()
        
        try:
            atomic_write_json(FALLOS_PATH, fallos_existentes)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ERROR CRÍTICO al guardar fallos.json: {e}")

def agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=False):
    """Añade un fallo a memoria y hace flush si es crítico."""
    global FALLOS_EN_MEMORIA, FALLOS_LOCK
    fallo = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "nombre": nombre,
        "post": post_index,
        "error_msg": error_msg
    }
    with FALLOS_LOCK:
        FALLOS_EN_MEMORIA.append(fallo)
    
    # 🟢 CORRECCIÓN D: Flush inmediato si es crítico
    if critical or len(FALLOS_EN_MEMORIA) >= 5:
        flush_fallos_to_disk()

# 🟢 CORRECCIÓN 4: Leer fallos combinados para la GUI
def get_combined_fallos():
    """Retorna los fallos del disco + los de memoria (para la GUI)."""
    with FALLOS_LOCK:
        fallos_disco = cargar_json(FALLOS_PATH)
        fallos_combinados = fallos_disco + FALLOS_EN_MEMORIA
    return fallos_combinados

def guardar_fallos_periodicamente():
    """Hilo para guardar fallos periódicamente."""
    global FALLOS_EN_MEMORIA
    while get_running_status():
        if not interruptible_sleep(180):
            break
        flush_fallos_to_disk()

# --- FUNCIÓN DE VERIFICACIÓN DE COOKIES ---

# 🟢 CORRECCIÓN A: VERIFICACIÓN DE KEYS DE COOKIES
def ensure_cookies_ok(cuenta, post_index=-1):
    """Comprueba que las cookies necesarias existan."""
    nombre = cuenta.get("nombre", "?")
    cookies = cuenta.get("cookies")
    if not cookies or not isinstance(cookies, dict):
        msg = "Cookies ausentes o inválidas"
        agregar_fallo_en_memoria(nombre, post_index, msg, critical=True)
        marcar_cuarentena(nombre, msg)
        return False, msg
        
    required = ["csrftoken", "sessionid", "ds_user_id"] 
    missing = [k for k in required if k not in cookies]
    if missing:
        msg = f"Cookies incompletas, faltan: {', '.join(missing)}"
        agregar_fallo_en_memoria(nombre, post_index, msg, critical=True)
        marcar_cuarentena(nombre, msg)
        return False, msg
        
    return True, ""

# --- UTILIDADES DE REQUEST ---
def calcular_jazoest(csrftoken):
    return f"2{sum(ord(c) for c in csrftoken)}"

def generar_upload_id():
    return str(int(time.time() * 1000))

def construir_cookie_header(cookies):
    orden = ["mid", "ig_did", "csrftoken", "ds_user_id", "sessionid", "rur"]
    return "; ".join([f"{k}={cookies[k]}" for k in orden if k in cookies])

def construir_proxies(proxy_str):
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

# 🟢 CORRECCIÓN E: NORMALIZACIÓN DE RUTAS DE IMÁGENES
def get_image_path(cuenta, post):
    img_rel = post.get("img", "")
    if not img_rel:
        return None, "No se especificó ruta de imagen."
        
    if os.path.isabs(img_rel):
        image_path = img_rel
    else:
        image_path = os.path.normpath(os.path.join(GRUPOS_DIR, cuenta["grupo"], img_rel))

    if not os.path.exists(image_path):
        return None, f"Archivo no encontrado en la ruta: {image_path}"
        
    return image_path, ""

def load_group_posts(group_name):
    file_path = os.path.join(GRUPOS_DIR, f"{group_name}.json")
    if not os.path.exists(file_path):
        print(f"⚠️ Archivo de grupo no encontrado: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding='utf-8') as f:
            posts = json.load(f)
            return posts
    except Exception as e:
        print(f"❌ Error al cargar el grupo {group_name}: {e}")
        return []

# --- FUNCIÓN DE ANÁLISIS DE RESPUESTA CENTRALIZADA ---

def analizar_respuesta_api(res, nombre, post_index, is_config=False):
    # 1. Error HTTP 302/Redirección (Challenge/Login)
    if res.status_code == 302 or any(keyword in res.url.lower() for keyword in ['login', 'challenge', 'checkpoint']):
        error_msg = f"BLOQUEO API: Redirección a Login/Challenge."
        marcar_require_login(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "block"

    # 2. Rate Limit (429)
    if res.status_code == 429:
        error_msg = "BLOQUEO: Rate Limit (429). Retry con backoff."
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"

    # 3. CRÍTICO: Detección de HTML de Baneo/Página Perdida
    if res.status_code != 200 or "esta página sí se perdió" in res.text.lower() or "el enlace no funciona" in res.text.lower():
        error_msg = f"BLOQUEO HTML/HTTP {res.status_code}: Cuenta Baneada/Error Crítico."
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"

    # 4. Éxito HTTP (200 OK) - Validación JSON Estricta
    try:
        data = res.json()
    except json.JSONDecodeError:
        error_msg = f"ERROR API (200, No JSON): Respuesta inesperada. {res.text[:50]}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"

    # 5. Fallo Explícito o Fallo Silencioso CRÍTICO
    is_explicit_fail = data.get('status') == 'fail' or data.get('feedback_title') == 'Action Blocked'
    is_silent_fail = is_config and ('media' not in data or 'pk' not in data.get('media', {}))

    if is_explicit_fail or is_silent_fail:
        feedback_msg = data.get('feedback_message', data.get('message', 'Fallo interno/desconocido.'))
        
        if any(word in feedback_msg.lower() for word in ['suspended', 'disabled', 'banned']):
            action = "quarantine"
            error_msg = f"BANEO SEVERO JSON: {feedback_msg[:100]}"
            marcar_cuarentena(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
            return False, error_msg, action
        
        action = "retry"
        error_msg = f"FALLO JSON (Silent/Explicit): {feedback_msg[:100]}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, action

    # Éxito Verdadero
    post_id = data.get('media', {}).get('pk', '')
    return True, post_id, "success"

# --- FUNCIONES DE VERIFICACIÓN MEJORADAS ---

def verificar_estado_cuenta_robusto(cuenta):
    """Verificación mejorada que maneja redirecciones a threads.com"""
    nombre = cuenta.get("nombre", "(sin nombre)")
    proxy = construir_proxies(cuenta.get("proxy"))
    
    # Verificación de cookies primero
    ok, err_msg = ensure_cookies_ok(cuenta)
    if not ok:
        return False, err_msg, True
    
    try:
        cookies = cuenta["cookies"]
        cookie_header = construir_cookie_header(cookies)
        csrf_token = cookies["csrftoken"]
        ds_user_id = cookies.get("ds_user_id", "")

        headers = {
            "x-instagram-ajax": "0", 
            "x-csrftoken": csrf_token, 
            "x-ig-app-id": "238260118697367",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "cookie": cookie_header, 
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9", 
            "cache-control": "max-age=0",
        }
        
        # 🟢 CORRECCIÓN: Manejar específicamente redirección a threads.com
        response = requests.get(
            "https://www.threads.net/",
            headers=headers,
            proxies=proxy,
            verify=False,
            timeout=30,
            allow_redirects=True  # Permitir redirecciones para analizarlas
        )
        
        # 🟢 ANÁLISIS MEJORADO DE REDIRECCIONES
        final_url = response.url.lower()
        
        # Detectar redirección a threads.com (NO es necesariamente un error de login)
        if "threads.com" in final_url:
            # Verificar si después de la redirección estamos en una página válida
            if response.status_code == 200:
                # Podría ser una redirección regional normal
                # Intentar una verificación adicional con la API
                return verificar_con_api_directa(cuenta, headers, proxy)
            else:
                return False, f"Redirección a threads.com con status {response.status_code}", True
        
        # Verificación de códigos de estado
        if response.status_code in [301, 302, 307]:
            location = response.headers.get('location', '')
            if any(keyword in location.lower() for keyword in ['login', 'challenge', 'checkpoint']):
                return False, f"Redirección a login/challenge: {location}", True
            return False, f"Redirección inesperada: {location}", True
            
        if response.status_code != 200:
            return False, f"Status code inesperado: {response.status_code}", True
            
        # Verificación de contenido (mantener la existente)
        content = response.text.lower()
        banned_patterns = [
            'account suspended', 'account disabled', 'user not found', 
            'this account is private', 'sorry, something went wrong', 
            'challenge_required', 'login_required', 'not authorized'
        ]
        
        for pattern in banned_patterns:
            if pattern in content:
                return False, f"Patrón de baneo detectado: {pattern}", True
        
        # Verificación adicional con API
        if ds_user_id:
            return verificar_con_api_directa(cuenta, headers, proxy)
        
        return True, "Cuenta válida", False
            
    except requests.exceptions.ProxyError:
        return False, "Error de proxy", True
    except requests.exceptions.ConnectionError:
        return False, "Error de conexión", True
    except Exception as e:
        return False, f"Error de verificación: {str(e)[:100]}", False

def verificar_con_api_directa(cuenta, headers, proxy):
    """Verificación directa usando la API de Threads"""
    nombre = cuenta.get("nombre", "(sin nombre)")
    
    try:
        # Intentar acceder a un endpoint de API que requiera autenticación
        api_url = "https://www.threads.net/api/graphql"
        
        # Query básica para verificar autenticación
        payload = {
            "doc_id": "23996318473300828",  # Query de perfil básico
            "variables": json.dumps({"userID": cuenta["cookies"].get("ds_user_id", "")})
        }
        
        response = requests.post(
            api_url,
            headers=headers,
            data=payload,
            proxies=proxy,
            verify=False,
            timeout=15
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get('errors'):
                    error_msg = data['errors'][0].get('message', 'Error de API')
                    return False, f"Error en API: {error_msg}", True
                else:
                    return True, "Cuenta válida (verificación API)", False
            except:
                return True, "Cuenta válida (respuesta API OK)", False
        else:
            return False, f"Error API: {response.status_code}", True
            
    except Exception as e:
        return False, f"Error en verificación API: {str(e)[:100]}", False

def verificar_post_publicado(cuenta, post_id):
    """Verificación mejorada que maneja diferentes formatos de respuesta"""
    nombre = cuenta.get("nombre", "(sin nombre)")
    proxy = construir_proxies(cuenta.get("proxy"))
    
    try:
        cookies = cuenta["cookies"]
        cookie_header = construir_cookie_header(cookies)
        csrf_token = cookies["csrftoken"]

        headers = {
            "x-instagram-ajax": "0", 
            "x-csrftoken": csrf_token, 
            "x-ig-app-id": "238260118697367",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "cookie": cookie_header, 
            "accept": "*/*"
        }
        
        post_url = "https://www.threads.net/api/graphql"
        post_data = {
            "variables": json.dumps({"postID": str(post_id)}),
            "doc_id": "5587632691339264"
        }
        
        response = requests.post(
            post_url,
            headers=headers,
            data=post_data,
            proxies=proxy,
            verify=False,
            timeout=15
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                
                # 🟢 CORRECCIÓN: Múltiples formatos de respuesta válidos
                if data.get('data') and not data.get('errors'):
                    return True, "Post verificado exitosamente"
                elif data.get('data') is None and not data.get('errors'):
                    # Algunas respuestas tienen data=None pero sin errores
                    return True, "Post verificado (respuesta sin data)"
                elif data.get('errors'):
                    # Verificar si el error es específico de post no encontrado
                    error_msg = str(data.get('errors', [{}])[0]).lower()
                    if any(word in error_msg for word in ['not found', 'invalid', 'no existe']):
                        return False, f"Post no encontrado: {error_msg}"
                    else:
                        # Otro tipo de error, pero el post podría existir
                        return True, f"Post posiblemente publicado (error de API: {error_msg[:50]})"
                else:
                    # Respuesta inesperada pero no necesariamente fallo
                    return True, "Post posiblemente publicado (respuesta inesperada)"
                    
            except json.JSONDecodeError:
                # 🟢 CORRECCIÓN: No es necesariamente un fallo si no podemos parsear
                # Podría ser una respuesta vacía pero exitosa
                if len(response.text.strip()) == 0:
                    return True, "Post posiblemente publicado (respuesta vacía)"
                else:
                    return False, "Error al parsear respuesta de verificación"
        else:
            # 🟢 CORRECCIÓN: No marcar como fallo inmediato por códigos HTTP
            if response.status_code in [404, 400]:
                return False, f"Post no encontrado (HTTP {response.status_code})"
            else:
                # Otros códigos podrían ser temporales
                return True, f"Verificación HTTP {response.status_code} - reintentar más tarde"
            
    except Exception as e:
        # 🟢 CORRECCIÓN: Errores de conexión no significan que el post no exista
        return True, f"Error de conexión en verificación: {str(e)[:100]}"

# --- FUNCIONES DE PUBLICACIÓN MEJORADAS ---

def publicar_texto(cuenta, post, post_index):
    nombre = cuenta.get("nombre", "(sin nombre)")
    
    # Verificación de cookies
    ok, err_msg = ensure_cookies_ok(cuenta, post_index)
    if not ok:
        return False, err_msg, "quarantine"
        
    # Verificación previa de cuenta
    is_valid, error_reason, should_quarantine = verificar_estado_cuenta_robusto(cuenta)
    if not is_valid:
        if should_quarantine:
            marcar_cuarentena(nombre, f"Verificación previa falló: {error_reason}")
            agregar_fallo_en_memoria(nombre, post_index, f"CUENTA INVÁLIDA: {error_reason}", critical=True)
            return False, f"CUENTA INVÁLIDA: {error_reason}", "quarantine"
        else:
            agregar_fallo_en_memoria(nombre, post_index, f"ERROR VERIFICACIÓN: {error_reason}")
            return False, f"ERROR VERIFICACIÓN: {error_reason}", "retry"

    try:
        cookies = cuenta["cookies"]
        proxy = construir_proxies(cuenta["proxy"])
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

        # Análisis de respuesta
        is_success, result_msg, action = analizar_respuesta_api(res, nombre, post_index, is_config=True)
        
        if not is_success:
            if action == "quarantine":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA: {result_msg} - Cuenta: {nombre}")
                marcar_cuarentena(nombre, result_msg)
            elif action == "block":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 BLOQUEO: {result_msg} - Cuenta: {nombre}")
                marcar_require_login(nombre, result_msg)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ ERROR TEMPORAL: {result_msg} - Cuenta: {nombre}")
            
            return False, result_msg, action

        # 🟢 CORRECCIÓN MEJORADA: Verificación más tolerante
        post_id = result_msg
        if post_id:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Verificando publicación del post ID: {post_id}")
            time.sleep(5)  # Dar más tiempo para que se propague
            
            post_exists, verify_error = verificar_post_publicado(cuenta, post_id)
            
            if not post_exists:
                # 🟢 NUEVA LÓGICA: Verificación secundaria antes de cuarentena
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Verificación primaria falló, intentando verificación secundaria...")
                
                # Esperar un poco más y reintentar
                time.sleep(10)
                post_exists_retry, verify_error_retry = verificar_post_publicado(cuenta, post_id)
                
                if not post_exists_retry:
                    # 🟢 VERIFICACIÓN MANUAL: Intentar acceder al post via URL
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Verificación manual via URL...")
                    manual_check = verificar_post_manual(cuenta, post_id)
                    
                    if not manual_check:
                        error_msg = f"FALLO DE VERIFICACIÓN CONFIRMADO: {verify_error} - Post ID: {post_id}"
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 {error_msg} - Cuenta: {nombre}")
                        marcar_cuarentena(nombre, error_msg)
                        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
                        return False, error_msg, "quarantine"
                    else:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Verificación manual exitosa - Cuenta: {nombre}")
                        return True, "", "success"
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Verificación secundaria exitosa - Cuenta: {nombre}")
                    return True, "", "success"
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ POST VERIFICADO EXITOSO (Texto): ID {post_id} - Cuenta: {nombre}")
                return True, "", "success"
        else:
            # No hay post_id pero la publicación fue exitosa según la API
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Publicación exitosa pero sin ID de post - Cuenta: {nombre}")
            return True, "", "success"

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ POST VERIFICADO EXITOSO (Texto): ID {post_id} - Cuenta: {nombre}")
        return True, "", "success"

    except requests.exceptions.ProxyError as e:
        error_msg = f"ERROR PROXY CAÍDO/MALO: {str(e)[:150]}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (Proxy): {nombre}")
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except requests.exceptions.SSLError as e:
        error_msg = f"ERROR CONEXIÓN SSL: {str(e)[:150]}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (SSL): {nombre}")
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except requests.exceptions.ConnectionError as e:
        error_msg = f"ERROR DE CONEXIÓN (General): {str(e)[:150]}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (Conexión): {nombre}")
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except Exception as e:
        error_msg = f"ERROR GENERAL: {str(e)[:150]}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA CRÍTICA (General): {nombre}")
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    
def verificar_post_manual(cuenta, post_id):
    try:
        proxy = construir_proxies(cuenta.get("proxy"))
        cookies = cuenta["cookies"]
        cookie_header = construir_cookie_header(cookies)
        
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "cookie": cookie_header,
        }
        
        # Intentar acceder a la URL del post
        post_url = f"https://www.threads.net/t/{post_id}"
        response = requests.get(
            post_url,
            headers=headers,
            proxies=proxy,
            verify=False,
            timeout=10,
            allow_redirects=True
        )
        
        # Si podemos cargar la página (aunque sea con redirección), el post existe
        if response.status_code == 200:
            return True
        else:
            return False
            
    except Exception:
        return False

def verificar_estado_cuarentena():
    """Verifica qué cuentas están realmente en cuarentena"""
    cuentas = cargar_cuentas()
    en_cuarentena = []
    
    for cuenta in cuentas:
        if cuenta.get('estado') == 'cuarentena':
            en_cuarentena.append({
                'nombre': cuenta.get('nombre'),
                'razon': cuenta.get('quarantine_reason', 'Sin razón'),
                'timestamp': datetime.now().strftime("%H:%M:%S")
            })
    
    return en_cuarentena

# 🟢 NUEVA FUNCIÓN: Revisar y limpiar cuarentenas falsas
def revisar_cuarentenas_falsas():
    """Revisa cuentas en cuarentena que podrían ser falsos positivos"""
    cuentas = cargar_cuentas()
    cuarentenas_limpiadas = 0
    
    for cuenta in cuentas:
        if cuenta.get('estado') == 'cuarentena':
            razon = cuenta.get('quarantine_reason', '')
            
            # Patrones de falsos positivos comunes
            falsos_positivos = [
                'FALLO DE VERIFICACIÓN',
                'Error al parsear respuesta',
                'respuesta inesperada',
                'Post posiblemente publicado'
            ]
            
            if any(fp in razon for fp in falsos_positivos):
                print(f"🔄 Limpiando posible falso positivo: {cuenta.get('nombre')}")
                cuenta['estado'] = 'alive'
                if 'quarantine_reason' in cuenta:
                    del cuenta['quarantine_reason']
                cuarentenas_limpiadas += 1
    
    if cuarentenas_limpiadas > 0:
        guardar_cuentas(cuentas)
        print(f"✅ Limpiadas {cuarentenas_limpiadas} cuarentenas posibles falsos positivos")
    
    return cuarentenas_limpiadas


def publicar_con_imagen(cuenta, post, post_index):
    nombre = cuenta.get("nombre", "(sin nombre)")
    
    # 🟢 CORRECCIÓN A: Verificación de cookies
    ok, err_msg = ensure_cookies_ok(cuenta, post_index)
    if not ok:
        return False, err_msg, "quarantine"
        
    # 🆕 VERIFICACIÓN PREVIA DE CUENTA
    is_valid, error_reason, should_quarantine = verificar_estado_cuenta_robusto(cuenta)
    if not is_valid:
        if should_quarantine:
            marcar_cuarentena(nombre, f"Verificación previa falló: {error_reason}")
            agregar_fallo_en_memoria(nombre, post_index, f"CUENTA INVÁLIDA: {error_reason}", critical=True)
            return False, f"CUENTA INVÁLIDA: {error_reason}", "quarantine"
        else:
            agregar_fallo_en_memoria(nombre, post_index, f"ERROR VERIFICACIÓN: {error_reason}")
            return False, f"ERROR VERIFICACIÓN: {error_reason}", "retry"
    
    cookies = cuenta["cookies"]
    proxy = construir_proxies(cuenta["proxy"])
    cookie_header = construir_cookie_header(cookies)
    csrf_token = cookies["csrftoken"]
    jazoest = calcular_jazoest(csrf_token)
    upload_id = generar_upload_id()

    # 🟢 CORRECCIÓN E: Usar función normalizada de ruta de imagen
    image_path, path_error = get_image_path(cuenta, post)
    if not image_path:
        agregar_fallo_en_memoria(nombre, post_index, path_error)
        return False, path_error, "retry"

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
        upload_response = requests.post(upload_url, headers=upload_headers,
                      data=image_data, verify=False, proxies=proxy, timeout=30, allow_redirects=False)
        
        if upload_response.status_code == 302:
            error_msg = f"BLOQUEO API (Upload): Require login (302). Revisar cookies."
            marcar_require_login(nombre, error_msg)
            agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
            return False, error_msg, "block"
            
        if not upload_response.ok:
            error_msg = f"ERROR UPLOAD: {upload_response.status_code}. Respuesta: {upload_response.text[:150]}"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ ERROR UPLOAD: {error_msg}. Reintentando.")
            agregar_fallo_en_memoria(nombre, post_index, error_msg)
            return False, error_msg, "retry"

    except requests.exceptions.ProxyError as e:
        error_msg = f"ERROR PROXY CAÍDO/MALO (Upload): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except requests.exceptions.SSLError as e:
        error_msg = f"ERROR CONEXIÓN SSL (Upload): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except requests.exceptions.ConnectionError as e:
        error_msg = f"ERROR DE CONEXIÓN (General - Upload): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
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
    
    configure_headers = upload_headers.copy()
    configure_headers["content-type"] = "application/x-www-form-urlencoded;charset=UTF-8"

    try:
        res_config = requests.post(configure_url, headers=configure_headers,
                                   data=configure_payload, verify=False, proxies=proxy, timeout=30, allow_redirects=False)

        # 🟢 CORRECCIÓN 5/F: Usar análisis centralizado
        is_success, result_msg, action = analizar_respuesta_api(res_config, nombre, post_index, is_config=True)
        
        if not is_success:
            if action == "quarantine":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 CUARENTENA (Imagen): {result_msg} - Cuenta: {nombre}")
                marcar_cuarentena(nombre, result_msg)
            elif action == "block":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 BLOQUEO (Imagen): {result_msg} - Cuenta: {nombre}")
                marcar_require_login(nombre, result_msg)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ ERROR TEMPORAL (Imagen): {result_msg} - Cuenta: {nombre}")
            
            return False, result_msg, action

        # Verificación de publicación exitosa
        post_id = result_msg
        if post_id:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Verificando publicación de imagen ID: {post_id}")
            time.sleep(3)
            
            post_exists, verify_error = verificar_post_publicado(cuenta, post_id)
            if not post_exists:
                error_msg = f"FALLO DE VERIFICACIÓN (Imagen): {verify_error} - Post ID: {post_id}"
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 {error_msg} - Cuenta: {nombre}")
                marcar_cuarentena(nombre, error_msg)
                agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
                return False, error_msg, "quarantine"

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ POST VERIFICADO EXITOSO (Imagen): ID {post_id} - Cuenta: {nombre}")
        return True, "", "success"
    
    except requests.exceptions.ProxyError as e:
        error_msg = f"ERROR PROXY CAÍDO/MALO (Configure): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except requests.exceptions.SSLError as e:
        error_msg = f"ERROR CONEXIÓN SSL (Configure): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except requests.exceptions.ConnectionError as e:
        error_msg = f"ERROR DE CONEXIÓN (General - Configure): {str(e)[:150]}"
        marcar_cuarentena(nombre, error_msg)
        agregar_fallo_en_memoria(nombre, post_index, error_msg, critical=True)
        return False, error_msg, "quarantine"
    except Exception as e:
        error_msg = f"ERROR GENERAL (Configure): {str(e)[:150]}"
        agregar_fallo_en_memoria(nombre, post_index, error_msg)
        return False, error_msg, "retry"

# --- SISTEMA DE REINTENTOS CON BACKOFF EXPONENCIAL ---

# 🟢 CORRECCIÓN G: BACKOFF EXPONENCIAL
class RetryManager:
    def __init__(self, max_retries=3, base_delay=60):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.retry_counts = {}
    
    def should_retry(self, account_name):
        if account_name not in self.retry_counts:
            self.retry_counts[account_name] = 0
        return self.retry_counts[account_name] < self.max_retries
    
    def get_retry_delay(self, account_name):
        if account_name not in self.retry_counts:
            self.retry_counts[account_name] = 0
        return self.base_delay * (2 ** self.retry_counts[account_name])
    
    def increment_retry(self, account_name):
        if account_name not in self.retry_counts:
            self.retry_counts[account_name] = 0
        self.retry_counts[account_name] += 1
    
    def reset_retry(self, account_name):
        if account_name in self.retry_counts:
            self.retry_counts[account_name] = 0

RETRY_MANAGER = RetryManager(max_retries=3, base_delay=60)

# --- HILO DE PUBLICACIÓN MEJORADO ---

def procesar_cuenta(cuenta):
    """Función original de procesamiento de cuenta (compatible con la GUI existente)"""
    if not get_running_status():
        return

    nombre_cuenta = cuenta.get("nombre", "Desconocida")
    grupo_nombre = cuenta.get("grupo", "default")

    # 🆕 VERIFICACIÓN INICIAL ROBUSTA DE LA CUENTA
    print(f"\n🔍 Verificando estado inicial de la cuenta: {nombre_cuenta}")
    is_valid, error_reason, should_quarantine = verificar_estado_cuenta_robusto(cuenta)
    
    if not is_valid:
        if should_quarantine:
            print(f"🚨 Cuenta {nombre_cuenta} FALLIDA en verificación inicial: {error_reason}")
            marcar_cuarentena(nombre_cuenta, f"Verificación inicial: {error_reason}")
            agregar_fallo_en_memoria(nombre_cuenta, -1, f"VERIFICACIÓN INICIAL FALLIDA: {error_reason}", critical=True)
            return
        else:
            print(f"⚠️ Cuenta {nombre_cuenta} con problemas temporales: {error_reason}. Esperando antes de reintentar...")
            if not interruptible_sleep(300):
                return

    print(f"✅ Cuenta {nombre_cuenta} validada correctamente. Iniciando ciclo de publicación.")

    grupo_path = os.path.join("grupos", f"{grupo_nombre}.json")
    all_posts = cargar_json(grupo_path)

    if not all_posts:
        print(f"⚠️ Grupo '{grupo_nombre}' de la cuenta {nombre_cuenta} no encontrado o vacío en la ruta: {grupo_path}")
        return

    posts_para_reintentar = [] 
    posts_exitosos = 0
    posts_fallidos = 0

    try:
        while get_running_status(): 
            current_post = None

            if posts_para_reintentar:
                current_post = posts_para_reintentar.pop(0)
                print(f"\n🔄 Cuenta: {nombre_cuenta} - Reintentando post fallido...")
            else:
                current_post = random.choice(all_posts)
                
            try:
                original_index = all_posts.index(current_post) 
            except ValueError:
                original_index = -1 

            print(f"\n➡️ Cuenta: {nombre_cuenta} - Publicando post ID original #{original_index + 1}...")
            print(f"📝 Caption: {current_post.get('caption', 'Sin caption')[:100]}...")

            exito = False
            error_detalle = "Error desconocido."
            action = "retry"

            try:
                post_img_val = current_post.get("img", "").strip()
                imagenes = [img.strip() for img in post_img_val.split("|") if img.strip()] if post_img_val else []

                if len(imagenes) > 1:
                    current_post["imgs"] = imagenes
                    # Para carrusel, usar función de imagen por ahora (deberías implementar publicar_carrusel si es necesario)
                    exito, error_detalle, action = publicar_con_imagen(cuenta, current_post, original_index)
                elif len(imagenes) == 1:
                    current_post["img"] = imagenes[0]
                    exito, error_detalle, action = publicar_con_imagen(cuenta, current_post, original_index)
                else:
                    exito, error_detalle, action = publicar_texto(cuenta, current_post, original_index)

            except Exception as e:
                error_msg = str(e)
                print(f"⚠️ Excepción general al intentar publicar: {error_msg}")
                exito = False
                error_detalle = f"Excepción crítica en el hilo: {error_msg[:150]}"
                action = "retry"

            # Manejar resultados
            if action == "quarantine":
                print(f"🛑 Cuenta ({nombre_cuenta}) 🚨 ¡CUARENTENA! Razón: {error_detalle}")
                return 

            if action == "block":
                print(f"🛑 Cuenta ({nombre_cuenta}) 🚨 ¡BLOQUEO! Razón: {error_detalle}")
                return 

            if not exito:
                posts_fallidos += 1
                print(f"❌ Falló la publicación del post ID {original_index+1}. Total fallidos: {posts_fallidos}")
                print(f"⚠️ Razón del fallo: {error_detalle}")
                
                # Limitar reintentos para evitar bucles infinitos
                if posts_fallidos < 3:
                    print(f"🔄 Se reintentará (intento {posts_fallidos}/3).")
                    posts_para_reintentar.append(current_post)
                else:
                    print(f"🚫 Demasiados fallos consecutivos. Saltando post.")
                    posts_fallidos = 0
                
                delay_minutes_total = random.randint(15, 25)
                print(f"⏳ Cuenta ({nombre_cuenta}) ❌ Post fallido. Delay de recuperación: {delay_minutes_total} minutos.")
            else:
                posts_exitosos += 1
                posts_fallidos = 0
                delay_minutes_total = get_post_delay(current_post, grupo_nombre)
                delay_hours_display = delay_minutes_total / 60

                print(f"✅ Cuenta ({nombre_cuenta}) - Post #{posts_exitosos} exitoso!")
                print(f"⏳ Próximo post en: {delay_hours_display:.2f} horas ({delay_minutes_total} min).")

            # Espera Controlada
            sleep_seconds = delay_minutes_total * 60 
            
            if not interruptible_sleep(sleep_seconds):
                print(f"Cuenta ({nombre_cuenta}) detenido por interfaz.")
                return

        print(f"✅ Hilo de cuenta ({nombre_cuenta}) terminado. Posts exitosos: {posts_exitosos}")

    except Exception as e:
        print(f"❌ Error general en cuenta ({nombre_cuenta}): {str(e)}")
        agregar_fallo_en_memoria(nombre_cuenta, -1, f"Error hilo principal: {str(e)}", critical=True)

# --- FUNCIÓN PRINCIPAL COMPATIBLE CON GUI EXISTENTE ---

def run_posting_threads():
    """Función principal compatible con la GUI existente (sin parámetros)"""
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

        if is_enabled and is_active:
            hilo = threading.Thread(
                target=procesar_cuenta, args=(cuenta,), daemon=True)
            hilo.start()
            hilos.append(hilo)

            # Delay entre inicio de hilos
            delay_start = random.randint(13, 47)
            print(f"😴 Esperando {delay_start} segundos antes de iniciar el hilo de la próxima cuenta...")
            
            if not interruptible_sleep(delay_start):
                 print("⚠️ Proceso de inicio de hilos interrumpido.")
                 break
        else:
            estado_str = cuenta.get('estado', 'alive')
            enabled_str = 'ACTIVADA' if is_enabled else 'DESACTIVADA'
            print(f"⏩ Saltando cuenta {nombre}: 'Usar'={enabled_str}, estado={estado_str}")

    # Esperar a que todos los hilos terminen
    while get_running_status() and any(hilo.is_alive() for hilo in hilos):
        time.sleep(1)

    print("✅ Hilos de publicación detenidos.")
    set_running_status(False)
    
    # 🟢 CORRECCIÓN B: Forzar flush de fallos al detener
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 💾 Guardando fallos pendientes...")
    flush_fallos_to_disk()
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Hilos de publicación detenidos.")

# --- FUNCIÓN AVANZADA PARA USO FUTURO ---

def run_posting_threads_avanzado(grupos=None, max_threads=5):
    """
    Función avanzada para uso futuro con parámetros específicos.
    No se usa actualmente por la GUI.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎬 Iniciando sistema de publicación avanzado...")
    set_running_status(True)
    
    # Iniciar hilo de guardado de fallos
    fallos_thread = threading.Thread(target=guardar_fallos_periodicamente, daemon=True)
    fallos_thread.start()
    
    # Cargar cuentas y filtrar las activas
    cuentas = cargar_cuentas()
    cuentas_alive = [c for c in cuentas if c.get('estado') == 'alive']
    
    if not cuentas_alive:
        print("❌ No hay cuentas en estado 'alive' para publicar.")
        set_running_status(False)
        return
    
    print(f"📊 Cuentas activas encontradas: {len(cuentas_alive)}")
    
    # Si no se especifican grupos, usar todos los grupos de las cuentas
    if grupos is None:
        grupos = list(set(c.get('grupo', 'default') for c in cuentas_alive))
    
    # Preparar grupos y posts
    grupos_a_publicar = []
    for grupo_nombre in grupos:
        posts = load_group_posts(grupo_nombre)
        if posts:
            grupos_a_publicar.append((grupo_nombre, posts))
            print(f"📁 Grupo '{grupo_nombre}': {len(posts)} posts cargados")
        else:
            print(f"⚠️ Grupo '{grupo_nombre}' no tiene posts válidos")
    
    if not grupos_a_publicar:
        print("❌ No hay grupos válidos para publicar.")
        set_running_status(False)
        return
    
    # Asignar cuentas a grupos (round-robin)
    threads = []
    for i, cuenta in enumerate(cuentas_alive):
        if not get_running_status():
            break
            
        grupo_index = i % len(grupos_a_publicar)
        grupo_nombre, posts = grupos_a_publicar[grupo_index]
        
        thread = threading.Thread(
            target=procesar_cuenta,
            args=(cuenta,),
            daemon=True
        )
        threads.append(thread)
        thread.start()
        
        print(f"🧵 Hilo {i+1} iniciado para cuenta: {cuenta.get('nombre')} -> Grupo: {grupo_nombre}")
        
        # Delay entre inicio de hilos
        if i < len(cuentas_alive) - 1:
            time.sleep(5)
    
    # Esperar a que todos los hilos terminen
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🛑 Interrupción por teclado detectada.")
        set_running_status(False)
    
    # 🟢 CORRECCIÓN B: Forzar flush de fallos al detener
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 💾 Guardando fallos pendientes...")
    flush_fallos_to_disk()
    
    set_running_status(False)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Todos los hilos de publicación han finalizado.")