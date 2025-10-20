# gui_app.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, Toplevel
import ttkbootstrap as ttb
import json
import os
import threading
import sys
import shutil
import time
import subprocess
from datetime import datetime
import csv
import random

# Asegurarse de que el directorio actual esté en el PATH para importar core_poster
sys.path.append(os.path.dirname(__file__))

# Constantes de Archivos
CUENTAS_PATH = "cuentas.json"
FALLOS_PATH = "fallos.json"
GRUPOS_DIR = "grupos"

# Claves de cookies esperadas y su ORDEN en el CSV
# El orden aquí DEFINE el orden en que deben estar las cookies separadas por | en el CSV
EXPECTED_COOKIE_KEYS = ["cb", "mid", "ig_did",
                        "ds_user_id", "csrftoken", "sessionid", "rur"]

# Claves MÍNIMAS esperadas para cada post dentro de un grupo para el CSV de Grupos
EXPECTED_POST_KEYS = ["caption", "img", "delay_min", "delay_max"]

# =================================================================
# BLOQUE DE IMPORTACIÓN CON DIAGNÓSTICO DE ERRORES CRÍTICOS
try:
    # Importar las funciones y la nueva configuración global de core_poster
    from core_poster import (
        run_posting_threads, set_running_status, get_running_status,
        cargar_json, update_delay_config, DELAY_CONFIG
    )
except ImportError as e:
    messagebox.showerror("Error de Importación",
                         f"Asegúrese de que el archivo 'core_poster.py' existe y contiene el código completo.\nError: {e}")
    sys.exit(1)
# =================================================================


# Crear directorios si no existen
if not os.path.exists(GRUPOS_DIR):
    os.makedirs(GRUPOS_DIR)

# --- Funciones de Gestión de Archivos para la GUI ---


def get_group_files():
    """Retorna una lista de nombres de grupos (sin la extensión .json)."""
    return sorted([f.replace('.json', '') for f in os.listdir(GRUPOS_DIR) if f.endswith('.json')])


def load_group_content(group_name):
    """Carga el contenido de un archivo de grupo (.json) como string JSON."""
    if not group_name:
        return ""
    path = os.path.join(GRUPOS_DIR, f"{group_name}.json")
    try:
        content = cargar_json(path)
        # Se asegura que el JSON sea legible/válido
        return json.dumps(content, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error al cargar el grupo {group_name}.json: {e}"


def save_group_content(group_name, content):
    """Guarda el contenido editado de un archivo de grupo (espera un string JSON)."""
    path = os.path.join(GRUPOS_DIR, f"{group_name}.json")
    try:
        data = json.loads(content)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # No mostrar messagebox aquí, se maneja en el método que llama
        return True
    except json.JSONDecodeError:
        messagebox.showerror(
            "Error", "Error: El JSON a guardar en el grupo no es válido.")
        return False
    except Exception as e:
        messagebox.showerror("Error al Guardar",
                             f"Error al guardar {group_name}.json: {e}")
        return False

# Función de carga (Asumiendo que usa json.load)
def load_accounts_data():
    if not os.path.exists(CUENTAS_PATH):
        return []
    try:
        with open(CUENTAS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # 💡 CORRECCIÓN CLAVE: Desanidar la lista
            # Si el JSON es [[cuenta1, cuenta2, ...]], extraemos la lista interna
            if isinstance(data, list) and len(data) == 1 and isinstance(data[0], list):
                return data[0]
                
            # Si el formato es correcto ([cuenta1, cuenta2, ...]), lo devolvemos tal cual
            return data

    except Exception as e:
        messagebox.showerror("Error de Carga", f"Error al cargar {CUENTAS_PATH}: {e}")
        return []


def load_fallos_data():
    """Carga la lista de fallos desde fallos.json."""
    try:
        if os.path.exists(FALLOS_PATH):
            with open(FALLOS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    except Exception:
        # Si el archivo está corrupto o vacío, retorna lista vacía
        return []

def save_group_data(group_name, posts):
    if not group_name:
        messagebox.showerror("Error", "El nombre del grupo no puede estar vacío.")
        return False
    
    # 1. Crear el directorio de imágenes del grupo
    group_dir = os.path.join(GRUPOS_DIR, group_name)
    os.makedirs(group_dir, exist_ok=True) 
    
    # CORRECCIÓN: Crear subcarpeta para imágenes
    imagenes_dir = os.path.join(group_dir, "imagenes")
    os.makedirs(imagenes_dir, exist_ok=True)
    
    # 2. Procesar posts para copiar imágenes a la carpeta del grupo
    for post in posts:
        img_path = post.get('img', '').strip()
        if img_path and os.path.exists(img_path):
            try:
                # Copiar imagen a la carpeta del grupo
                img_filename = os.path.basename(img_path)
                dest_path = os.path.join(imagenes_dir, img_filename)
                
                if not os.path.exists(dest_path):
                    shutil.copy2(img_path, dest_path)
                    print(f"📁 Imagen copiada: {img_filename}")
                
                # Actualizar la ruta en el post para usar ruta relativa
                post['img'] = os.path.join("imagenes", img_filename)
            except Exception as e:
                print(f"⚠️ Error copiando imagen {img_path}: {e}")

    # 3. Guardar el archivo JSON del grupo
    file_path = os.path.join(GRUPOS_DIR, f"{group_name}.json")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(posts, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        messagebox.showerror("Error de Guardado", f"No se pudo guardar el archivo del grupo: {e}")
        return False
    
# --- Clase Principal de la GUI ---


class PosterApp(ttb.Frame): # Se añade herencia de ttb.Frame para un uso más limpio de ttkbootstrap
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        master.title("🤖 Threads Poster Bot")
        master.geometry("1100x650")

        ttb.Style("flatly")
        
        # 🟢 CORRECCIÓN 1: Inicializar self.bot_thread a None para evitar AttributeError
        self.bot_thread = None

        # Usar la variable global IS_RUNNING importada
        # self.is_running = IS_RUNNING # No usamos esta variable local, sino la global importada
        self.selected_group = tk.StringVar(value="")

        # Variables internas para el editor de posts
        self.current_posts = []
        self.current_caption = tk.StringVar()
        self.current_img = tk.StringVar()
        self.current_delay_min = tk.StringVar()
        self.current_delay_max = tk.StringVar()

        self.notebook = ttb.Notebook(master)
        self.notebook.pack(pady=10, padx=10, expand=True, fill="both")

        # --- Creación de pestañas ---
        self.create_control_tab()
        self.create_quarantine_tab()
        self.create_accounts_tab()
        self.create_groups_tab()
        self.create_delay_tab()
        self.create_diagnostics_tab()

        # Configurar protocolo de cierre para detener el bot
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 💡 FIX 1: Iniciar la verificación de estado del bot (CRUCIAL para los botones)
        self.check_bot_status()

        # 💡 FIX 2/3: Iniciar el refresco periódico de la GUI (árboles)
        self.periodic_refresh()
        
    # --- Pestaña 1: Control ---
    def create_control_tab(self):
        control_frame = ttb.Frame(self.notebook, padding=10)
        self.notebook.add(control_frame, text="Control")

        button_container = ttb.Frame(control_frame)
        button_container.pack(pady=10, fill="x")

        # El estado inicial se gestiona en check_bot_status
        self.start_button = ttb.Button(
            button_container, text="▶️ Iniciar Bot", bootstyle="success", command=self.start_bot)
        self.start_button.pack(side=tk.LEFT, expand=True, padx=5)

        self.stop_button = ttb.Button(
            button_container, text="⏹️ Detener Bot", bootstyle="danger-outline", command=self.stop_bot)
        self.stop_button.pack(side=tk.LEFT, expand=True, padx=5)

        ttk.Label(control_frame, text="Log de Consola:",
                  bootstyle="primary").pack(pady=(20, 5), anchor="w")

        self.log_text = tk.Text(control_frame, height=20, wrap=tk.WORD,
                                state=tk.DISABLED, background="#222", foreground="#eee")
        self.log_text.pack(expand=True, fill="both")

        sys.stdout.write = lambda s: self.redirect_output(s)
        sys.stderr.write = lambda s: self.redirect_output(s, is_error=True)

    # --- Pestaña 2: Cuentas ---
    def create_accounts_tab(self):
        accounts_frame = ttb.Frame(self.notebook, padding=10)
        self.notebook.add(accounts_frame, text="Cuentas")

        table_container = ttb.LabelFrame(
            accounts_frame, text="Gestión de Cuentas Activas", padding=10)
        table_container.pack(pady=5, expand=True, fill="both")

        self.account_tree = ttk.Treeview(table_container, columns=(
            'Usar', 'Nombre', 'Grupo', 'Proxy', 'Estado'), show='headings', selectmode="extended")
        self.account_tree.heading('Usar', text='Usar', anchor=tk.CENTER)
        self.account_tree.heading('Nombre', text='Usuario', anchor=tk.CENTER)
        self.account_tree.heading(
            'Grupo', text='Grupo Asignado', anchor=tk.CENTER)
        self.account_tree.heading(
            'Proxy', text='Proxy (Usuario:Pass@IP:Puerto)', anchor=tk.W)
        self.account_tree.heading('Estado', text='Estado', anchor=tk.CENTER)

        self.account_tree.column(
            'Usar', width=50, anchor=tk.CENTER, stretch=False)
        self.account_tree.column(
            'Nombre', width=120, anchor=tk.CENTER, stretch=False)
        self.account_tree.column(
            'Grupo', width=100, anchor=tk.CENTER, stretch=False)
        self.account_tree.column('Proxy', minwidth=250, width=350, anchor=tk.W)
        self.account_tree.column(
            'Estado', width=80, anchor=tk.CENTER, stretch=False)
        self.account_tree.pack(side=tk.LEFT, expand=True, fill="both")

        vsb = ttk.Scrollbar(table_container, orient="vertical",
                            command=self.account_tree.yview)
        vsb.pack(side=tk.RIGHT, fill="y")
        self.account_tree.configure(yscrollcommand=vsb.set)

        self.update_account_tree()

        button_frame = ttb.Frame(accounts_frame)
        button_frame.pack(pady=10, fill="x")

        ttb.Button(button_frame, text="⬆️ Importar Cuentas (CSV)", bootstyle="primary",
                   command=self.import_accounts_from_csv).pack(side=tk.LEFT, padx=10)
        ttb.Button(button_frame, text="⬇️ Descargar Plantilla (CSV)", bootstyle="info",
                   command=self.download_csv_template).pack(side=tk.LEFT, padx=10)

        ttb.Separator(button_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, padx=15)

        ttb.Button(button_frame, text="✅ Activar Seleccionadas", bootstyle="success",
                   command=lambda: self.toggle_selected_accounts(True)).pack(side=tk.LEFT, padx=10)
        ttb.Button(button_frame, text="❌ Desactivar Seleccionadas", bootstyle="danger",
                   command=lambda: self.toggle_selected_accounts(False)).pack(side=tk.LEFT, padx=10)

        ttb.Separator(button_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, padx=15)

        ttb.Button(button_frame, text="✏️ Editar Cuenta", bootstyle="warning",
                   command=self.edit_selected_account).pack(side=tk.LEFT, padx=10)
        ttb.Button(button_frame, text="❌ Eliminar Cuenta", bootstyle="danger",
                   command=self.delete_selected_account).pack(side=tk.LEFT, padx=10)

        ttb.Button(button_frame, text="🔄 Recargar Tabla", bootstyle="secondary-outline",
                   command=self.update_account_tree).pack(side=tk.RIGHT, padx=10)

    # --- Pestaña 3: Grupos (Modificada para usar Treeview) ---
    def create_groups_tab(self):
        groups_frame = ttb.LabelFrame(
            self.notebook, text="Gestión de Archivos de Grupo (Posts)", padding=10)
        self.notebook.add(groups_frame, text="Grupos")

        # Contenedor de la tabla
        table_container = ttb.Frame(groups_frame)
        table_container.pack(pady=10, expand=True, fill="both")

        self.group_tree = ttk.Treeview(
            table_container, columns=('Nombre', 'Posts'), show='headings')
        
        info_label = ttb.Label(
        groups_frame, 
        text=f"🎯 Modo de delay actual: {'Individuales' if DELAY_CONFIG['use_individual_delays'] else 'General'}",
        bootstyle="info",
        font=("Arial", 9)
        )
        info_label.pack(pady=5, anchor="w") 

        self.group_tree.heading('Nombre', text='Nombre del Grupo', anchor=tk.W)
        self.group_tree.heading('Posts', text='# Posts', anchor=tk.CENTER)

        self.group_tree.column('Nombre', width=200, anchor=tk.W, stretch=True)
        self.group_tree.column(
            'Posts', width=100, anchor=tk.CENTER, stretch=False)

        vsb = ttk.Scrollbar(table_container, orient="vertical",
                            command=self.group_tree.yview)
        vsb.pack(side=tk.RIGHT, fill="y")
        self.group_tree.configure(yscrollcommand=vsb.set)
        self.group_tree.pack(side=tk.LEFT, expand=True, fill="both")

        self.update_group_tree()  # Carga inicial de la tabla

        button_frame = ttb.Frame(groups_frame)
        button_frame.pack(pady=10, fill="x")

        # Botones de gestión completos
        # FIX: Se corrigió el error AttributeError añadiendo el método import_posts_from_csv
        ttb.Button(button_frame, text="⬆️ Importar Posts (CSV)", bootstyle="primary",
                   command=self.import_posts_from_csv).pack(side=tk.LEFT, padx=5)
        ttb.Button(button_frame, text="⬇️ Descargar Plantilla (CSV)", bootstyle="info",
                   command=self.download_group_csv_template).pack(side=tk.LEFT, padx=5)

        ttb.Separator(button_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, padx=15)

        ttb.Button(button_frame, text="➕ Crear Grupo Nuevo", bootstyle="success",
                   command=self.create_new_group).pack(side=tk.LEFT, padx=5)
        # ESTE BOTÓN AHORA ABRE EL FORMULARIO/TABLA
        ttb.Button(button_frame, text="✏️ Editar Posts (Tabla)", bootstyle="warning",
                   command=self.edit_selected_group).pack(side=tk.LEFT, padx=5)
        ttb.Button(button_frame, text="❌ Eliminar Grupo", bootstyle="danger",
                   command=self.delete_selected_group).pack(side=tk.LEFT, padx=5)

        ttb.Button(button_frame, text="🔄 Recargar Tabla", bootstyle="secondary-outline",
                   command=self.update_group_tree).pack(side=tk.RIGHT, padx=5)
        ttb.Button(button_frame, text="📂 Abrir Carpeta Posts", bootstyle="secondary",
                   command=self.open_group_folder).pack(side=tk.RIGHT, padx=5)

    # --- Pestaña 4: Delay ---
    def create_delay_tab(self):
        """Crea la pestaña de configuración de delays con opciones individuales y generales."""
        delay_frame = ttb.LabelFrame(
            self.notebook, text="⏱️ Configuración de Delays (Minutos)", padding=15)
        self.notebook.add(delay_frame, text="Delay")

        # Variables de control
        self.min_delay_var = tk.StringVar(value=str(DELAY_CONFIG["min_minutes"]))
        self.max_delay_var = tk.StringVar(value=str(DELAY_CONFIG["max_minutes"]))
        self.use_individual_delays_var = tk.BooleanVar(
            value=DELAY_CONFIG["use_individual_delays"])

        # Frame principal con grid
        main_grid = ttb.Frame(delay_frame)
        main_grid.pack(fill="x", pady=10)

        # Sección de Delay General
        general_frame = ttb.LabelFrame(
            main_grid, text="🔄 Delay General para Todos los Posts", padding=10)
        general_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")

        # Configuración de delay general
        ttb.Label(general_frame, text="Delay Mínimo (Min):").grid(
            row=0, column=0, padx=5, pady=5, sticky="w")
        min_entry = ttb.Entry(
            general_frame, textvariable=self.min_delay_var, width=10)
        min_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttb.Label(general_frame, text="Delay Máximo (Min):").grid(
            row=1, column=0, padx=5, pady=5, sticky="w")
        max_entry = ttb.Entry(
            general_frame, textvariable=self.max_delay_var, width=10)
        max_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # Sección de Modo de Delay
        mode_frame = ttb.LabelFrame(main_grid, text="🎯 Modo de Delay", padding=10)
        mode_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        # Radio buttons para selección de modo
        self.individual_radio = ttb.Radiobutton(
            mode_frame,
            text="Usar Delays Individuales de Cada Post",
            variable=self.use_individual_delays_var,
            value=True,
            command=self.actualizar_estado_delay_mode
        )
        self.individual_radio.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.general_radio = ttb.Radiobutton(
            mode_frame,
            text="Usar Delay General para Todos los Posts",
            variable=self.use_individual_delays_var,
            value=False,
            command=self.actualizar_estado_delay_mode
        )
        self.general_radio.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        # Información del modo actual
        self.mode_info_label = ttb.Label(
            mode_frame,
            text="",
            bootstyle="info",
            font=("Arial", 9)
        )
        self.mode_info_label.grid(row=2, column=0, padx=5, pady=5, sticky="w")

        # Botón de aplicar
        apply_button = ttb.Button(
            delay_frame,
            text="💾 Aplicar Configuración de Delay",
            bootstyle="success",
            command=self.apply_delay_settings
        )
        apply_button.pack(pady=15)

        # Información adicional
        info_frame = ttb.Frame(delay_frame)
        info_frame.pack(fill="x", pady=10)

        ttb.Label(
            info_frame,
            text="💡 Información:",
            bootstyle="primary",
            font=("Arial", 10, "bold")
        ).pack(anchor="w")

        info_text = """
• Delays Individuales: Cada post usa sus propios valores de delay_min y delay_max
• Delay General: Todos los posts usan el mismo rango de delay configurado arriba
• Jitter: Se aplica una variación aleatoria de ±7 minutos a todos los delays
• Los delays de recuperación por fallos son siempre de 15-30 minutos
        """

        info_label = ttb.Label(
            info_frame,
            text=info_text,
            bootstyle="info",
            justify="left",
            font=("Arial", 9)
        )
        info_label.pack(anchor="w", pady=5)

        # Actualizar estado inicial
        self.actualizar_estado_delay_mode()

    def actualizar_estado_delay_mode(self):
        """Actualiza la información del modo de delay seleccionado."""
        if self.use_individual_delays_var.get():
            mode_text = "✅ Modo ACTUAL: Delays Individuales - Cada post usará sus delays específicos"
        else:
            mode_text = "✅ Modo ACTUAL: Delay General - Todos los posts usarán el mismo rango de delay"

        self.mode_info_label.config(text=mode_text)

    def apply_delay_settings(self):
        """Aplica la configuración de delay a core_poster.py y actualiza la GUI."""
        try:
            min_val = self.min_delay_var.get()
            max_val = self.max_delay_var.get()

            min_val_int = int(min_val)
            max_val_int = int(max_val)

            if min_val_int < 1 or max_val_int < 1:
                messagebox.showerror(
                    "Error de Validación", "Los valores de Delay deben ser mayores o iguales a 1 minuto.")
                return

            # Llama a la función del core para actualizar la configuración
            use_individual = self.use_individual_delays_var.get()
            
            update_delay_config(min_val, max_val, use_individual)

            # Accedemos a la variable global DELAY_CONFIG para mostrar los valores corregidos
            final_min = DELAY_CONFIG['min_minutes']
            final_max = DELAY_CONFIG['max_minutes']

            # Actualizar variables de la GUI con los valores corregidos/aplicados
            self.min_delay_var.set(str(final_min))
            self.max_delay_var.set(str(final_max))

            messagebox.showinfo(
                "Éxito", f"Configuración de Delay aplicada:\nMin: {final_min} min\nMax: {final_max} min")

        except ValueError:
            messagebox.showerror(
                "Error de Entrada", "Por favor, ingrese solo números enteros válidos para el Delay.")
        except Exception as e:
            messagebox.showerror(
                "Error", f"Error al aplicar la configuración de delay: {e}")

    # --- Pestaña 5: Cuarentena ---
    def create_quarantine_tab(self):
        """Crea la pestaña de Cuentas en Cuarentena."""
        quarantine_frame = ttb.Frame(self.notebook, padding=10)
        self.notebook.add(quarantine_frame, text="Cuarentena")

        tree_container = ttb.LabelFrame(
            quarantine_frame, text="Cuentas con Fallos Críticos de Proxy/Bloqueo (Detenidas)", padding=10)
        tree_container.pack(expand=True, fill="both", pady=5)

        self.quarantine_tree = ttk.Treeview(tree_container, columns=(
            'Nombre', 'Estado', 'Razón'), show='headings', selectmode="extended")

        self.quarantine_tree.heading(
            'Nombre', text='Usuario', anchor=tk.CENTER)
        self.quarantine_tree.heading('Estado', text='Estado', anchor=tk.CENTER)
        self.quarantine_tree.heading(
            'Razón', text='Razón del Bloqueo/Proxy Crítico', anchor=tk.W)

        self.quarantine_tree.column(
            'Nombre', width=150, anchor=tk.CENTER, stretch=False)
        self.quarantine_tree.column(
            'Estado', width=100, anchor=tk.CENTER, stretch=False)
        self.quarantine_tree.column('Razón', width=600, anchor=tk.W)

        vsb = ttk.Scrollbar(tree_container, orient="vertical",
                            command=self.quarantine_tree.yview)
        vsb.pack(side=tk.RIGHT, fill="y")
        self.quarantine_tree.configure(yscrollcommand=vsb.set)

        self.quarantine_tree.pack(side=tk.LEFT, expand=True, fill="both")

        self.update_quarantine_tree()

        # Botones de gestión
        button_frame = ttb.Frame(quarantine_frame)
        button_frame.pack(pady=10, fill="x")

        ttb.Button(button_frame, text="🟢 Restaurar Seleccionadas (Alive)", bootstyle="success",
                   command=self.restore_selected_quarantined).pack(side=tk.LEFT, padx=10)
        ttb.Button(button_frame, text="🔄 Recargar Lista", bootstyle="info-outline",
                   command=self.update_quarantine_tree).pack(side=tk.RIGHT, padx=10)
        
    def redirect_output(self, s, is_error=False):
        self.log_text.config(state=tk.NORMAL)
        if is_error:
            self.log_text.insert(tk.END, s, "error")
        else:
            self.log_text.insert(tk.END, s)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
    def check_bot_status_and_update_gui(self):        
        # 1. Actualizar las tablas (fuerza la recarga de cuentas.json)
        self.update_account_tree()
        self.update_fallos_tree() # Se incluye para ver los fallos detallados

        # 2. Verificar si el bot sigue corriendo usando la bandera global de core_poster
        if get_running_status():
            # Si sigue corriendo, programa esta función para que se ejecute de nuevo en 5 segundos (5000 ms)
            self.master.after(5000, self.check_bot_status_and_update_gui)
        else:
            # Si se detuvo, asegura el estado final de los botones.
            self.update_button_states()
            
    def update_button_states(self):        
        is_running = get_running_status()

        if hasattr(self, 'start_button') and hasattr(self, 'stop_button'):
            if is_running:
                # Bot corriendo: Deshabilitar Start, Habilitar Stop
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                # Opcional: Deshabilitar botones de configuración/carga mientras corre
                # if hasattr(self, 'load_accounts_button'): self.load_accounts_button.config(state=tk.DISABLED)
            else:
                # Bot detenido: Habilitar Start, Deshabilitar Stop
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                # Opcional: Habilitar botones de configuración/carga
                # if hasattr(self, 'load_accounts_button'): self.load_accounts_button.config(state=tk.NORMAL)
                    

    # --- Pestaña 6: Diagnóstico ---
    def create_diagnostics_tab(self):
        diag_frame = ttb.Frame(self.notebook, padding=10)
        self.notebook.add(diag_frame, text="Diagnóstico")

        button_container = ttb.Frame(diag_frame)
        button_container.pack(pady=10, fill="x")

        ttb.Button(button_container, text="🩺 Verificar Cuentas (Próx. Función)",
                   bootstyle="primary-outline", state=tk.DISABLED).pack(side=tk.LEFT, padx=5)
        ttb.Button(button_container, text="🔄 Recargar Log de Fallos", bootstyle="warning",
                   command=self.update_fallos_tree).pack(side=tk.RIGHT, padx=5)

        tree_container = ttb.LabelFrame(
            diag_frame, text="Historial de Errores (fallos.json)", padding=10)
        tree_container.pack(expand=True, fill="both", pady=5)

        # FIX: Se cambia 'PostIndex' a 'Post ID' y se corrige el ancho de columna
        self.fallos_tree = ttk.Treeview(tree_container, columns=(
            'Timestamp', 'Cuenta', 'Post ID', 'Error'), show='headings')

        self.fallos_tree.heading('Timestamp', text='Hora del Fallo', command=lambda: self.sort_treeview(
            self.fallos_tree, 'Timestamp', False))
        self.fallos_tree.heading('Cuenta', text='Cuenta')
        # FIX: Corrección del identificador de columna
        self.fallos_tree.heading('Post ID', text='Post #')
        self.fallos_tree.heading('Error', text='Tipo de Error')

        # FIX: Ancho de columna actualizado
        self.fallos_tree.column('Timestamp', width=180, anchor=tk.W)
        self.fallos_tree.column('Cuenta', width=120, anchor=tk.W)
        self.fallos_tree.column('Post ID', width=70, anchor=tk.CENTER)
        # 💡 FIX: Ancho aumentado para que el mensaje de error completo sea visible
        self.fallos_tree.column('Error', minwidth=200, width=450, anchor=tk.W)

        vsb_fallos = ttk.Scrollbar(
            tree_container, orient="vertical", command=self.fallos_tree.yview)
        vsb_fallos.pack(side=tk.RIGHT, fill="y")
        self.fallos_tree.configure(yscrollcommand=vsb_fallos.set)

        hsb_fallos = ttk.Scrollbar(
            tree_container, orient="horizontal", command=self.fallos_tree.xview)
        hsb_fallos.pack(side=tk.BOTTOM, fill="x")
        self.fallos_tree.configure(xscrollcommand=hsb_fallos.set)

        self.fallos_tree.pack(expand=True, fill="both")
        self.update_fallos_tree()

    # --- Métodos de Control y Utilidades ---

# -------------------------------------------------
# --- LÓGICA DE CONTROL DEL BOT (FIX CRÍTICO) ---
# -------------------------------------------------
    # def check_bot_status(self):
        
    #     # 1. Obtener el estado real del hilo
    #     thread_is_alive = hasattr(self, 'bot_thread') and self.bot_thread.is_alive()
        
    #     # 2. Actualizar el estado de los botones basándose en la vida del hilo
    #     if thread_is_alive:
    #         # El proceso está VIVO (Corriendo o terminando su ciclo)
    #         self.start_button.config(state=tk.DISABLED, bootstyle="secondary")
    #         self.stop_button.config(state=tk.NORMAL, bootstyle="danger")

    #         # Mostrar que está en proceso de detención si ya se le dio la señal de stop
    #         if not get_running_status():
    #              self.stop_button.config(text="⏳ Deteniendo...")
    #     else:
    #         # El proceso está MUERTO. El bot está realmente detenido.
    #         self.start_button.config(state=tk.NORMAL, bootstyle="success")
    #         self.stop_button.config(state=tk.DISABLED, bootstyle="danger-outline", text="⏹️ Detener Bot")
            
    #         # Si la bandera global era True y el thread ya murió, la reseteamos por seguridad
    #         if get_running_status():
    #             set_running_status(False)
    #             print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Bot Detenido Exitosamente (El hilo principal terminó).")


    #     # 3. Re-programar la ejecución
    #     self.master.after(500, self.check_bot_status)
        
    #     """
    #     Verifica el estado del bot y actualiza los botones Iniciar/Detener.
    #     Se llama periódicamente con master.after() cada 100ms.
    #     """
    #     is_running_flag = get_running_status()
    #     # Asegurarse de que self.bot_thread existe antes de llamar a is_alive()
    #     is_thread_alive = hasattr(
    #         self, 'bot_thread') and self.bot_thread and self.bot_thread.is_alive()

    #     if is_running_flag and is_thread_alive:
    #         # Bot corriendo: Desactivar Iniciar, Activar Detener
    #         self.start_button.config(state=tk.DISABLED, bootstyle="secondary")
    #         self.stop_button.config(state=tk.NORMAL, bootstyle="danger")
    #     else:
    #         # Bot detenido o hilo muerto: Activar Iniciar, Desactivar Detener
    #         self.start_button.config(state=tk.NORMAL, bootstyle="success")
    #         self.stop_button.config(
    #             state=tk.DISABLED, bootstyle="danger-outline")

    #     # Reprogramar la verificación cada 100ms para alta respuesta
    #     self.master.after(100, self.check_bot_status)

    def start_bot(self):   
        # Verificar si el hilo YA existe Y está vivo
        is_thread_alive = self.bot_thread and self.bot_thread.is_alive()
        
        if is_thread_alive:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Advertencia: El bot ya está en proceso de ejecución. Espere.")
            return
        
        # Si la bandera está en True pero el hilo está muerto (estado inconsistente), la reseteamos
        if get_running_status() and not is_thread_alive:
            set_running_status(False)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Iniciando el proceso de publicación...")
        set_running_status(True)
        
        self.update_button_states()
        
        self.bot_thread = threading.Thread(
            target=run_posting_threads, daemon=True)
        self.bot_thread.start()

        # 🟢 MODIFICACIÓN CLAVE: Iniciar el sistema de sondeo de la GUI (POLLING) 
        # Esto reemplaza self.check_bot_status() y fuerza el refresco de la tabla.
        self.check_bot_status_and_update_gui() 
    
    def stop_bot(self):
        """Detiene el bot enviando la señal y actualizando la UI."""
        
        # 🟢 CORRECCIÓN 3: Prevenir AttributeError y advertir si no hay nada que detener
        if self.bot_thread is None or not get_running_status():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ℹ️ El bot no está en funcionamiento.")
            return

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Solicitando la detención del bot. Esperando que los hilos finalicen...")
        set_running_status(False)  # Envía la señal de detención al core
        
        # El mensaje de "Bot detenido exitosamente" se emitirá ahora en check_bot_status
        # cuando el thread.is_alive() se vuelva False.

        # Actualizar el estado de los botones inmediatamente (para mostrar "Deteniendo...")
        self.check_bot_status()

    def check_bot_status(self):
             
        # 1. Obtener el estado real del hilo
        # Esto es True si el hilo existe y está ejecutando código
        thread_is_alive = self.bot_thread and self.bot_thread.is_alive()
        
        # 2. Obtener el estado de la bandera (la señal de stop enviada)
        is_running_flag = get_running_status()

        # 3. Lógica de Actualización de Botones
        if thread_is_alive:
            # El proceso está VIVO (Corriendo o terminando su ciclo)
            self.start_button.config(state=tk.DISABLED, bootstyle="secondary")
            self.stop_button.config(state=tk.NORMAL, bootstyle="danger")

            if not is_running_flag:
                 # Si el hilo está vivo PERO la bandera es False, significa que se presionó STOP
                 self.stop_button.config(text="⏳ Deteniendo...") 
                 
        else:
            # El proceso está MUERTO. El bot está realmente detenido.
            self.start_button.config(state=tk.NORMAL, bootstyle="success")
            self.stop_button.config(state=tk.DISABLED, bootstyle="danger-outline", text="⏹️ Detener Bot")
            
            # Si la bandera global era True y el thread ya murió, la reseteamos por seguridad
            if is_running_flag:
                 set_running_status(False)
                 print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Bot Detenido Exitosamente (El hilo principal terminó).")
            
            # Resetear la referencia al hilo una vez que ha muerto
            self.bot_thread = None

        # 4. Re-programar la ejecución (500ms es suficiente para monitorear)
        self.master.after(500, self.check_bot_status)

# -------------------------------------------------
# --- LÓGICA DE REFRESH Y ON_CLOSING ---
# -------------------------------------------------
    def periodic_refresh(self):
        """
        Refresca automáticamente las tablas de Cuentas, Cuarentena y Diagnóstico.
        """
        # Solo refrescamos los árboles para la pestaña actual
        current_tab_name = self.notebook.tab(self.notebook.select(), "text")

        # if current_tab_name in ["Cuentas", "Control"]:
        #     self.update_account_tree()

        # if current_tab_name == "Cuarentena":
        #     self.update_quarantine_tree()

        # if current_tab_name == "Diagnóstico":
        #     self.update_fallos_tree()
        
        self.update_account_tree()     
        self.update_quarantine_tree() 
        self.update_fallos_tree()

        # Reprogramar el refresco cada 3 segundos (3000 ms)
        self.periodic_refresh_id = self.master.after(
            3000, self.periodic_refresh)

    def on_closing(self):
        """Maneja el cierre de la ventana, asegurando la detención del bot."""
        # Cancelar el refresco periódico para evitar errores de Tcl al destruir la ventana
        if hasattr(self, 'periodic_refresh_id'):
            self.master.after_cancel(self.periodic_refresh_id)

        if get_running_status():
            if messagebox.askyesno("Detener Bot", "¿El bot está corriendo. Desea detenerlo y cerrar la aplicación?"):
                self.stop_bot()
                self.master.destroy()
            else:
                pass
        else:
            self.master.destroy()

    # --- Métodos de Gestión de Cuentas ---

    def get_selected_name(self, treeview):
        """Retorna el iid (que es el nombre/grupo) de la primera fila seleccionada o None."""
        selected_item = treeview.focus()
        if not selected_item:
            messagebox.showwarning(
                "Advertencia", "Por favor, seleccione un elemento de la tabla.")
            return None
        return selected_item

    def update_account_tree(self):
        """Carga y muestra las cuentas en la tabla de la pestaña Cuentas."""

        # 💡 PASO 1: GUARDAR SELECCIÓN ACTUAL
        # Guarda los iids (que son los nombres de las cuentas) de los ítems seleccionados.
        selected_iids = self.account_tree.selection()
        
        # 1. Limpiar la tabla existente 
        for i in self.account_tree.get_children():
            self.account_tree.delete(i)

        # 2. Cargar los datos de las cuentas
        cuentas = load_accounts_data()

        # 3. Obtener opciones de grupo para el menú desplegable de edición
        self.group_options = get_group_files()

        # 4. Insertar cada cuenta en la tabla
        for cuenta in cuentas:
            if not isinstance(cuenta, dict):
            # Imprimir una advertencia y saltar el elemento incorrecto
                print(f"Advertencia: Se saltó un elemento de cuenta no válido (no es un diccionario): {cuenta}")
                continue # Pasa al siguiente elemento del bucle
            
            nombre = cuenta.get('nombre', 'N/A')
            grupo = cuenta.get('grupo', 'N/A')
            proxy = cuenta.get('proxy', 'N/A')
            estado = cuenta.get('estado', 'alive')
            enabled = cuenta.get('enabled', True)

            # Formato visual para la columna 'Usar'
            usar_display = "✅" if enabled else "❌"
            
            # Etiquetas de color para el estado visual
            tags = ()
            if estado == 'bloqueo':
                tags = ('blocked',)
            elif estado == 'quarantine':
                tags = ('quarantine',)
            elif not enabled:
                tags = ('disabled',)

            # Insertar la fila en el Treeview, usando el nombre como iid
            self.account_tree.insert('', tk.END, iid=nombre, values=(
                usar_display, nombre, grupo, proxy, estado 
            ), tags=tags)

        # 💡 PASO 2: RESTAURAR SELECCIÓN
        # Re-selecciona los ítems que estaban seleccionados antes del refresh.
        # Solo re-selecciona si el iid (nombre de cuenta) existe en la tabla.
        existing_iids = self.account_tree.get_children()
        iids_to_restore = [iid for iid in selected_iids if iid in existing_iids]
        
        if iids_to_restore:
            self.account_tree.selection_set(iids_to_restore)
            # Opcional: Asegurarse de que el primer elemento seleccionado sea visible
            if iids_to_restore:
                 self.account_tree.see(iids_to_restore[0])

        # 5. Configuración de estilos/tags para la tabla
        self.account_tree.tag_configure('blocked', foreground='red')
        # ... (Mantener el resto de la configuración de tags) ...
        self.account_tree.tag_configure('disabled', foreground='gray') 

        # 6. Actualizar la tabla de cuarentena (si se incluye)
        self.update_quarantine_tree()

    def update_quarantine_tree(self):
        """Muestra solo las cuentas en estado 'quarantine' o 'require_login'."""
        for i in self.quarantine_tree.get_children():
            self.quarantine_tree.delete(i)

        all_accounts = load_accounts_data()
        quarantined_accounts = [
    # Solo incluye la cuenta si ES un diccionario Y su estado cumple la condición
    acc for acc in all_accounts
    if isinstance(acc, dict) and (
        acc.get('estado', 'alive') == 'quarantine' or 
        acc.get('estado') == 'bloqueo' or 
        acc.get('estado') == 'require_login'
    )
]

        if not quarantined_accounts:
            self.quarantine_tree.insert('', tk.END, values=(
                '', 'No hay cuentas en Cuarentena/Bloqueo. ¡Todo en orden! 🟢', ''), tags=('ok_quarantine',))
            self.quarantine_tree.tag_configure(
                'ok_quarantine', foreground='green')
            return

        for account in quarantined_accounts:
            nombre = account.get('nombre', 'N/A')
            estado = account.get('estado', 'N/A')

            if estado == 'quarantine':
                razon = account.get('quarantine_reason',
                                    'Proxy Crítico Desconocido')
                tag = 'quarantine'
            elif estado == 'require_login':
                razon = account.get(
                    'block_reason', 'Bloqueo/Require Login Desconocido')
                tag = 'login_block'
            else:
                continue

            self.quarantine_tree.insert('', tk.END, values=(
                nombre, estado.upper(), razon), tags=(tag,), iid=nombre)

        self.quarantine_tree.tag_configure(
            'quarantine', foreground='darkorange')
        self.quarantine_tree.tag_configure('login_block', foreground='red')

    def restore_selected_quarantined(self):
        """Restaura las cuentas seleccionadas de 'quarantine'/'require_login' a 'alive'."""
        selected_iids = self.quarantine_tree.selection()
        if not selected_iids:
            messagebox.showwarning(
                "Advertencia", "Debe seleccionar al menos una cuenta para restaurar.")
            return

        confirm = messagebox.askyesno(
            "Confirmar Restauración",
            f"¿Está seguro de que desea restaurar {len(selected_iids)} cuenta(s) a estado 'alive'? Esto permitirá que el bot intente usarlas de nuevo. Asegúrese de haber corregido el proxy o las cookies."
        )

        if not confirm:
            return

        restored_count = 0
        try:
            for iid in selected_iids:
                account_name = iid  # El iid del Treeview es el nombre de la cuenta

                # Llama a la función del core para actualizar el estado
                _update_account_state(account_name, "alive")
                restored_count += 1

            messagebox.showinfo(
                "Éxito", f"{restored_count} cuenta(s) restauradas a 'alive'.")

            self.update_account_tree()  # Recargar ambas tablas

        except Exception as e:
            messagebox.showerror("Error de Restauración",
                                 f"Error al restaurar las cuentas: {e}")

    def toggle_selected_accounts(self, enabled_status):
        """Activa o desactiva la bandera 'enabled' de las cuentas seleccionadas."""
        selected_items = self.account_tree.selection()
        if not selected_items:
            messagebox.showwarning(
                "Advertencia", "Por favor, seleccione una o más cuentas para modificar.")
            return

        action_text = 'ACTIVAR' if enabled_status else 'DESACTIVAR'
        respuesta = messagebox.askyesno(
            "Confirmar Acción",
            f"¿Está seguro de que desea {action_text} {len(selected_items)} cuenta(s) seleccionada(s)?"
        )

        if not respuesta:
            return

        cuentas_modificadas = 0
        cuentas = load_accounts_data()

        for item_id in selected_items:
            # El iid del Treeview es el nombre de la cuenta
            nombre_cuenta = item_id

            for cuenta in cuentas:
                if cuenta.get('nombre') == nombre_cuenta:
                    # 💡 Establece el nuevo valor de 'enabled'
                    cuenta['enabled'] = enabled_status

                    # Si se activa una cuenta en cuarentena, la pasamos a alive para reintento
                    if enabled_status and cuenta.get('estado') != 'alive':
                        cuenta['estado'] = 'alive'
                        cuenta.pop('quarantine_reason', None)
                        cuenta.pop('block_reason', None)

                    cuentas_modificadas += 1
                    break

        if cuentas_modificadas > 0:
            guardar_cuentas(cuentas)
            self.update_account_tree()  # Recargar la tabla para mostrar los cambios
            messagebox.showinfo(
                "Éxito", f"{cuentas_modificadas} cuenta(s) han sido {action_text} correctamente.")
        else:
            messagebox.showerror(
                "Error", "No se encontraron las cuentas seleccionadas en la base de datos.")

    def delete_selected_account(self):
        """Elimina la cuenta seleccionada de cuentas.json."""
        account_name = self.get_selected_name(self.account_tree)
        if not account_name:
            return

        respuesta = messagebox.askyesno(
            "Confirmar Eliminación",
            f"¿Está seguro de que desea eliminar permanentemente la cuenta '{account_name}'?"
        )

        if not respuesta:
            return

        cuentas = load_accounts_data()

        # Filtrar la lista de cuentas para excluir la seleccionada
        nueva_lista_cuentas = [
            c for c in cuentas if c.get('nombre') != account_name]

        if len(nueva_lista_cuentas) < len(cuentas):
            guardar_cuentas(nueva_lista_cuentas)
            self.update_account_tree()
            messagebox.showinfo(
                "Éxito", f"Cuenta '{account_name}' eliminada correctamente.")
        else:
            messagebox.showerror(
                "Error", f"No se encontró la cuenta '{account_name}'.")

    # --- Funciones de Importación / Exportación CSV ---

    def download_csv_template(self):
        """Descarga una plantilla CSV para cuentas."""

        # Definir la estructura básica del CSV (las cookies deben ir en el orden de EXPECTED_COOKIE_KEYS)
        header = ["nombre", "grupo", "proxy", "enabled", "cookies"]

        # Ejemplo con la cadena de cookies
        cookie_example = "|".join([f"<{key}>" for key in EXPECTED_COOKIE_KEYS])

        # Datos de ejemplo
        data = [
            ["user_ejemplo1", "grupoA", "user:pass@192.168.1.1:8080",
                "True", cookie_example],
            ["user_ejemplo2", "grupoB", "", "True", cookie_example],
        ]

        # Pide al usuario dónde guardar el archivo
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="plantilla_cuentas.csv"
        )

        if filepath:
            try:
                with open(filepath, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerow(header)
                    writer.writerows(data)
                messagebox.showinfo(
                    "Éxito", f"Plantilla guardada en:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Error al Guardar",
                                     f"Error al guardar el archivo: {e}")

    def import_accounts_from_csv(self):
        """Importa cuentas desde un archivo CSV y las agrega a cuentas.json."""
        filepath = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv")]
        )
        if not filepath:
            return

        try:
            cuentas_existentes = cargar_cuentas()
            cuentas_por_nombre = {c['nombre']: c for c in cuentas_existentes}
            nuevas_cuentas = 0
            cuentas_actualizadas = 0

            with open(filepath, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)

                # Verificar las cabeceras requeridas
                if not all(key in reader.fieldnames for key in ["nombre", "cookies"]):
                    messagebox.showerror(
                        "Error", "El archivo CSV debe contener al menos las columnas 'nombre' y 'cookies'.")
                    return

                for row in reader:
                    nombre = row.get('nombre', '').strip()
                    cookies_str = row.get('cookies', '').strip()
                    proxy_str = row.get('proxy', '').strip()
                    enabled_str = row.get('enabled', 'True').strip().lower()

                    if not nombre or not cookies_str:
                        print(f"⏩ Saltando fila incompleta: {row}")
                        continue

                    # 1. Procesar Cookies
                    cookie_values = cookies_str.split('|')
                    if len(cookie_values) != len(EXPECTED_COOKIE_KEYS):
                        print(
                            f"⚠️ Saltando cuenta {nombre}: Faltan cookies. Se esperan {len(EXPECTED_COOKIE_KEYS)}, se encontraron {len(cookie_values)}")
                        continue

                    cookies_obj = dict(
                        zip(EXPECTED_COOKIE_KEYS, cookie_values))

                    # 2. Determinar el estado 'enabled'
                    is_enabled = enabled_str in ('true', '1', 'yes', 'on')

                    # 3. Crear/Actualizar objeto de cuenta
                    nueva_cuenta_data = {
                        'nombre': nombre,
                        'grupo': row.get('grupo', 'default').strip(),
                        'proxy': proxy_str,
                        'cookies': cookies_obj,
                        'estado': 'alive',  # Siempre inicia como alive
                        'enabled': is_enabled
                    }

                    if nombre in cuentas_por_nombre:
                        # Si existe, actualiza solo los campos importantes
                        existente = cuentas_por_nombre[nombre]
                        existente.update(nueva_cuenta_data)
                        cuentas_actualizadas += 1
                    else:
                        # Si es nueva, la añade a la lista
                        cuentas_existentes.append(nueva_cuenta_data)
                        cuentas_por_nombre[nombre] = nueva_cuenta_data
                        nuevas_cuentas += 1

            # 4. Guardar y actualizar
            guardar_cuentas(cuentas_existentes)
            self.update_account_tree()

            messagebox.showinfo(
                "Importación Completa",
                f"Importación terminada:\n"
                f"Cuentas nuevas añadidas: {nuevas_cuentas}\n"
                f"Cuentas existentes actualizadas: {cuentas_actualizadas}"
            )

        except FileNotFoundError:
            messagebox.showerror("Error", "Archivo no encontrado.")
        except Exception as e:
            messagebox.showerror("Error de Importación",
                                 f"Ocurrió un error al leer el CSV: {e}")

    def edit_selected_account(self):
        """Abre una ventana de diálogo para editar los campos principales y las cookies de la cuenta seleccionada. Incluye el botón Guardar."""
        account_name = self.get_selected_name(self.account_tree)
        if not account_name:
            return

        accounts = load_accounts_data()
        selected_account = next(
            (acc for acc in accounts if acc.get('nombre') == account_name), None)

        if not selected_account:
            messagebox.showerror(
                "Error", "No se encontró la cuenta para editar.")
            return

        # --- Obtener datos iniciales ---
        initial_proxy = selected_account.get('proxy', '')
        initial_group = selected_account.get('grupo', 'default')
        initial_enabled = selected_account.get('enabled', True)

        # Objeto de cookies original para la comparación en el guardado
        initial_cookies_obj = selected_account.get('cookies', {})

        # --- Crear Ventana de Edición ---
        editor_window = Toplevel(self.master)
        editor_window.title(f"Editar Cuenta: {account_name}")
        editor_window.transient(self.master)
        editor_window.grab_set()
        editor_window.geometry("750x650")

        edit_frame = ttb.Frame(editor_window, padding=20)
        edit_frame.pack(expand=True, fill="both")

        # --- Variables de control ---
        proxy_var = tk.StringVar(value=initial_proxy)
        group_var = tk.StringVar(value=initial_group)
        enabled_var = tk.BooleanVar(value=initial_enabled)

        # Usamos un diccionario para almacenar las variables de las cookies
        cookie_vars = {key: tk.StringVar(value=initial_cookies_obj.get(
            key, '')) for key in EXPECTED_COOKIE_KEYS}

        # --- Campos Principales ---
        ttb.Label(edit_frame, text=f"Editando: {account_name}", bootstyle="primary").pack(
            pady=(0, 15), anchor="w")

        # Proxy
        ttb.Label(
            edit_frame, text="Proxy (user:pass@ip:port):").pack(pady=(5, 0), anchor="w")
        ttb.Entry(edit_frame, textvariable=proxy_var,
                  width=80).pack(pady=(0, 10), anchor="w")

        # Grupo
        ttb.Label(edit_frame, text="Grupo Asignado:").pack(
            pady=(5, 0), anchor="w")

        # Recargar lista de grupos para el Combobox
        group_options = get_group_files()
        # Asegurar que 'default' es una opción
        group_options.insert(0, 'default')

        ttb.Combobox(edit_frame, textvariable=group_var, values=group_options,
                     state="readonly", width=30).pack(pady=(0, 10), anchor="w")

        # Estado (Enabled)
        ttb.Checkbutton(edit_frame, text="Cuenta Habilitada (Enabled)",
                        bootstyle="success-round-toggle", variable=enabled_var).pack(pady=(5, 15), anchor="w")

        # --- Seccion de Cookies ---
        ttb.Label(edit_frame, text="Cookies Requeridas (Copiar/Pegar con Cuidado)",
                  bootstyle="info").pack(pady=(10, 5), anchor="w")

        cookies_frame = ttb.Frame(edit_frame)
        cookies_frame.pack(fill="x", pady=(0, 20))

        # Crear entradas para cada cookie
        for i, key in enumerate(EXPECTED_COOKIE_KEYS):
            row = i
            ttb.Label(cookies_frame, text=f"{key}:", width=15).grid(
                row=row, column=0, padx=5, pady=2, sticky="w")
            ttb.Entry(cookies_frame, textvariable=cookie_vars[key], width=60).grid(
                row=row, column=1, padx=5, pady=2, sticky="w")

        # --- Función de Guardado ---
        def save_and_close():
            try:
                new_proxy = proxy_var.get().strip()
                new_group = group_var.get().strip()
                new_enabled = enabled_var.get()
                new_cookies_obj = {key: var.get().strip()
                                   for key, var in cookie_vars.items()}

                # Validación simple de cookies
                if not all(new_cookies_obj.values()):
                    messagebox.showwarning(
                        "Advertencia", "Todas las cookies son obligatorias. Por favor, asegúrese de que no estén vacías.")
                    return

                # Crear el objeto de cuenta actualizado
                updated_account = {
                    'nombre': account_name,
                    'grupo': new_group,
                    'proxy': new_proxy,
                    'cookies': new_cookies_obj,
                    'enabled': new_enabled
                }

                # Mantener estado si no se está reactivando una cuenta de cuarentena
                if not new_enabled and selected_account.get('estado') != 'alive':
                    updated_account['estado'] = selected_account.get('estado')
                elif new_enabled:
                    # Si se activa, forzar estado a 'alive' para que el bot la recoja
                    updated_account['estado'] = 'alive'
                    updated_account.pop('quarantine_reason', None)
                    updated_account.pop('block_reason', None)

                # Actualizar la lista principal
                all_accounts = load_accounts_data()
                found = False
                for i, acc in enumerate(all_accounts):
                    if acc.get('nombre') == account_name:
                        # Usar .update() para mantener campos que no estamos editando (como quarantine_reason)
                        all_accounts[i].update(updated_account)
                        found = True
                        break

                if found:
                    guardar_cuentas(all_accounts)
                    self.update_account_tree()
                    editor_window.destroy()
                    messagebox.showinfo(
                        "Éxito", f"Cuenta '{account_name}' actualizada correctamente.")
                else:
                    messagebox.showerror(
                        "Error", "Error interno al encontrar la cuenta para guardar.")

            except Exception as e:
                messagebox.showerror(
                    "Error al Guardar", f"Ocurrió un error inesperado al guardar: {e}")

        # --- Botones de Guardado ---
        button_frame = ttb.Frame(edit_frame)
        button_frame.pack(pady=10, fill="x")

        ttb.Button(button_frame, text="💾 Guardar Cambios", bootstyle="success",
                   command=save_and_close).pack(side=tk.LEFT, padx=10)
        ttb.Button(button_frame, text="Cancelar", bootstyle="secondary",
                   command=editor_window.destroy).pack(side=tk.LEFT, padx=10)

        # Bloquear la ventana principal hasta que se cierre esta
        editor_window.wait_window(editor_window)

    # --- Funciones de Grupos ---

    def update_group_tree(self):
        """Carga y muestra los archivos de grupo en la tabla."""
        for i in self.group_tree.get_children():
            self.group_tree.delete(i)

        group_names = get_group_files()

        for name in group_names:
            path = os.path.join(GRUPOS_DIR, f"{name}.json")
            try:
                content = cargar_json(path)
                num_posts = len(content)
            except Exception:
                num_posts = "ERROR"

            self.group_tree.insert('', tk.END, iid=name,
                                   values=(name, num_posts))

    def create_new_group(self):
        """Crea un nuevo archivo de grupo con contenido JSON vacío ([]) o de ejemplo."""
        new_name = simpledialog.askstring(
            "Nuevo Grupo", "Ingrese el nombre para el nuevo grupo de posts:", parent=self.master)

        if new_name:
            # Limpiar y validar el nombre del archivo
            clean_name = "".join(c for c in new_name if c.isalnum() or c in (
                ' ', '_')).strip().replace(' ', '_')
            if not clean_name:
                messagebox.showwarning(
                    "Advertencia", "El nombre de grupo no es válido.")
                return

            path = os.path.join(GRUPOS_DIR, f"{clean_name}.json")
            if os.path.exists(path):
                messagebox.showwarning(
                    "Advertencia", f"El grupo '{clean_name}' ya existe.")
                return

            # Crear el archivo con una lista JSON vacía
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=2, ensure_ascii=False)

                messagebox.showinfo(
                    "Éxito", f"Grupo '{clean_name}' creado exitosamente en {GRUPOS_DIR}.")
                self.update_group_tree()

            except Exception as e:
                messagebox.showerror(
                    "Error", f"Error al crear el archivo: {e}")

    def edit_selected_group(self):
        """Abre el editor de posts en formato de tabla para el grupo seleccionado."""
        selected_group = self.get_selected_name(self.group_tree)
        if not selected_group:
            return

        self.selected_group.set(selected_group)
        self.show_post_editor(selected_group)

    def delete_selected_group(self):
        """Elimina el archivo de grupo seleccionado."""
        group_name = self.get_selected_name(self.group_tree)
        if not group_name:
            return

        respuesta = messagebox.askyesno(
            "Confirmar Eliminación",
            f"¿Está seguro de que desea eliminar permanentemente el grupo de posts '{group_name}'? Se eliminará el archivo JSON correspondiente."
        )

        if not respuesta:
            return

        path = os.path.join(GRUPOS_DIR, f"{group_name}.json")
        try:
            os.remove(path)
            messagebox.showinfo(
                "Éxito", f"Grupo '{group_name}' eliminado correctamente.")
            self.update_group_tree()
        except FileNotFoundError:
            messagebox.showerror(
                "Error", f"El archivo del grupo '{group_name}' no se encontró.")
        except Exception as e:
            messagebox.showerror("Error", f"Error al eliminar el grupo: {e}")

    def open_group_folder(self):
        """Abre la carpeta de grupos en el explorador de archivos del sistema."""
        try:
            if sys.platform == "win32":
                os.startfile(GRUPOS_DIR)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", GRUPOS_DIR])
            else:
                subprocess.Popen(["xdg-open", GRUPOS_DIR])
        except FileNotFoundError:
            messagebox.showerror(
                "Error", f"No se pudo abrir la carpeta: {GRUPOS_DIR}")
        except Exception as e:
            messagebox.showerror(
                "Error", f"Ocurrió un error al intentar abrir la carpeta: {e}")

    # --- Editor de Posts (Ventana Secundaria) ---

    def show_post_editor(self, group_name):
        """Abre la ventana para editar los posts de un grupo en formato de tabla."""
        editor_window = Toplevel(self.master)
        editor_window.title(f"Editor de Posts - Grupo: {group_name}")
        editor_window.transient(self.master)
        editor_window.grab_set()
        editor_window.geometry("1200x700")

        main_frame = ttb.Frame(editor_window, padding=10)
        main_frame.pack(expand=True, fill="both")

        # --- Variables de control ---
        # Usamos variables de instancia para que sean accesibles en los métodos de gestión de posts
        self.current_posts = self.load_posts_for_editor(group_name)

        # --- Tabla de Posts ---
        tree_frame = ttb.LabelFrame(
            main_frame, text="Posts del Grupo (Doble Clic para Editar)", padding=5)
        tree_frame.pack(expand=True, fill="both", pady=10)

        self.post_tree = ttk.Treeview(tree_frame, columns=(
            'Index', 'Caption (Snippet)', 'Img File', 'Delay Min', 'Delay Max'), show='headings')

        self.post_tree.heading('Index', text='#', anchor=tk.CENTER)
        self.post_tree.heading(
            'Caption (Snippet)', text='Contenido/Caption (Extracto)', anchor=tk.W)
        self.post_tree.heading(
            'Img File', text='Archivo de Imagen', anchor=tk.W)
        self.post_tree.heading(
            'Delay Min', text='Delay Min (Min)', anchor=tk.CENTER)
        self.post_tree.heading(
            'Delay Max', text='Delay Max (Min)', anchor=tk.CENTER)

        self.post_tree.column(
            'Index', width=50, anchor=tk.CENTER, stretch=False)
        self.post_tree.column('Caption (Snippet)',
                              minwidth=200, width=400, anchor=tk.W)
        self.post_tree.column('Img File', minwidth=150, width=300, anchor=tk.W)
        self.post_tree.column('Delay Min', width=100, anchor=tk.CENTER)
        self.post_tree.column('Delay Max', width=100, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.post_tree.yview)
        vsb.pack(side=tk.RIGHT, fill="y")
        self.post_tree.configure(yscrollcommand=vsb.set)

        self.post_tree.pack(side=tk.LEFT, expand=True, fill="both")

        self.post_tree.bind(
            '<Double-1>', lambda e: self.open_post_edit_dialog(editor_window))

        self.populate_post_tree()

        # --- Botones de Control ---
        button_frame = ttb.Frame(main_frame)
        button_frame.pack(fill="x", pady=10)

        ttb.Button(button_frame, text="➕ Agregar Nuevo Post", bootstyle="success",
                   command=lambda: self.open_post_edit_dialog(editor_window, is_new=True)).pack(side=tk.LEFT, padx=5)
        ttb.Button(button_frame, text="❌ Eliminar Post Seleccionado", bootstyle="danger",
                   command=self.delete_selected_post).pack(side=tk.LEFT, padx=5)
        ttb.Button(button_frame, text="💾 Guardar Cambios en JSON", bootstyle="primary",
                   command=lambda: self.save_posts_to_group(group_name, self.current_posts)).pack(side=tk.RIGHT, padx=5)
        ttb.Button(button_frame, text="Cerrar Editor", bootstyle="secondary",
                   command=lambda: editor_window.destroy()).pack(side=tk.RIGHT, padx=5)

        editor_window.protocol("WM_DELETE_WINDOW", lambda: self.on_post_editor_closing(
            editor_window, group_name))

        editor_window.wait_window(editor_window)

    def on_post_editor_closing(self, editor_window, group_name):
        """Maneja el cierre del editor de posts, preguntando si guardar o descartar."""
        if messagebox.askyesno("Guardar Cambios", f"¿Desea guardar los cambios realizados en el grupo '{group_name}' antes de cerrar?"):
            if self.save_posts_to_group(group_name, self.current_posts, show_success=False):
                editor_window.destroy()
            # Si el guardado falla, la ventana permanece abierta
        else:
            editor_window.destroy()

    def load_posts_for_editor(self, group_name):
        """Carga el JSON del grupo y lo retorna como lista de posts."""
        path = os.path.join(GRUPOS_DIR, f"{group_name}.json")
        try:
            return cargar_json(path)
        except Exception:
            # Si hay error (o archivo vacío) retorna lista vacía
            return []

    def populate_post_tree(self):
        """Rellena la tabla de posts con el contenido actual de self.current_posts."""
        for i in self.post_tree.get_children():
            self.post_tree.delete(i)

        for i, post in enumerate(self.current_posts):
            index = i + 1
            caption_snippet = post.get(
                'caption', 'N/A').strip()[:50] + ('...' if len(post.get('caption', 'N/A')) > 50 else '')
            img_file = os.path.basename(post.get('img', 'N/A'))
            delay_min = post.get('delay_min', 'N/A')
            delay_max = post.get('delay_max', 'N/A')

            # Usar el índice (i) como iid para facilitar la referencia en la lista
            self.post_tree.insert('', tk.END, iid=str(i), values=(
                index, caption_snippet, img_file, delay_min, delay_max))

    def open_post_edit_dialog(self, parent_window, is_new=False):
        """Abre un diálogo para editar o crear un post."""

        post_index = None
        post_data = {}

        if not is_new:
            selected_item = self.post_tree.focus()
            if not selected_item:
                messagebox.showwarning(
                    "Advertencia", "Por favor, seleccione un post para editar.")
                return

            # El iid es el índice en la lista self.current_posts
            post_index = int(selected_item)
            post_data = self.current_posts[post_index]

            dialog_title = f"Editar Post #{post_index + 1}"
        else:
            post_data = {key: '' for key in EXPECTED_POST_KEYS}
            post_data['delay_min'] = 30  # Valores por defecto
            post_data['delay_max'] = 60
            dialog_title = "Crear Nuevo Post"

        # --- Crear Ventana de Edición de Post ---
        edit_dialog = Toplevel(parent_window)
        edit_dialog.title(dialog_title)
        edit_dialog.transient(parent_window)
        edit_dialog.grab_set()
        edit_dialog.geometry("800x600")

        dialog_frame = ttb.Frame(edit_dialog, padding=20)
        dialog_frame.pack(expand=True, fill="both")

        # --- Variables de control ---
        caption_var = tk.StringVar(value=post_data.get('caption', ''))
        img_var = tk.StringVar(value=post_data.get('img', ''))
        delay_min_var = tk.StringVar(value=str(post_data.get('delay_min', 30)))
        delay_max_var = tk.StringVar(value=str(post_data.get('delay_max', 60)))

        # --- Campos del formulario ---

        # Caption
        ttb.Label(
            dialog_frame, text="Caption/Contenido (Markdown soportado):").pack(pady=(5, 0), anchor="w")
        caption_text = tk.Text(dialog_frame, height=10, width=70, wrap=tk.WORD)
        caption_text.insert(tk.END, post_data.get('caption', ''))
        caption_text.pack(pady=(0, 10), fill="x", expand=False)

        # Imagen
        ttb.Label(
            dialog_frame, text="Ruta Absoluta a Imagen/Video (Local):").pack(pady=(5, 0), anchor="w")
        img_entry = ttb.Entry(dialog_frame, textvariable=img_var, width=60)
        img_entry.pack(pady=(0, 5), fill="x", expand=False, side=tk.LEFT)
        ttb.Button(dialog_frame, text="Buscar Archivo...", bootstyle="info-outline",
                   command=lambda: self.select_image_file(img_var)).pack(side=tk.LEFT, padx=5)

        # Delay
        delay_frame = ttb.Frame(dialog_frame)
        delay_frame.pack(pady=10, fill="x", anchor="w")
        
        if DELAY_CONFIG["use_individual_delays"]:
            info_text = "💡 Los delays individuales están HABILITADOS - Este post usará sus delays específicos"
        else:
            info_text = "💡 Los delays individuales están DESHABILITADOS - Este post usará el delay general"
    
        ttb.Label(
            delay_frame, 
            text=info_text,
            bootstyle="info",
            font=("Arial", 8)
        ).pack(anchor="w")

        ttb.Label(delay_frame, text="Delay Mínimo (Min):").pack(
            side=tk.LEFT, padx=(0, 5))
        ttb.Entry(delay_frame, textvariable=delay_min_var,
                  width=10).pack(side=tk.LEFT, padx=(0, 20))

        ttb.Label(delay_frame, text="Delay Máximo (Min):").pack(
            side=tk.LEFT, padx=(0, 5))
        ttb.Entry(delay_frame, textvariable=delay_max_var,
                  width=10).pack(side=tk.LEFT)

        # --- Función de Guardado del Post ---
        def save_post_data():
            try:
                # 1. Obtener valores
                new_caption = caption_text.get("1.0", tk.END).strip()
                new_img = img_var.get().strip()
                new_delay_min = int(delay_min_var.get())
                new_delay_max = int(delay_max_var.get())

                # 2. Validación
                if not new_caption and not new_img:
                    messagebox.showwarning(
                        "Advertencia", "Un post debe tener al menos un caption o un archivo de imagen/video.")
                    return

                if new_delay_min < 1 or new_delay_max < 1 or new_delay_min > new_delay_max:
                    messagebox.showwarning(
                        "Advertencia", "Los valores de delay deben ser válidos (min >= 1, max >= 1, min <= max).")
                    return

                # 3. Crear el nuevo objeto post
                new_post_data = {
                    'caption': new_caption,
                    'img': new_img,
                    'delay_min': new_delay_min,
                    'delay_max': new_delay_max
                }

                # 4. Actualizar la lista principal
                if is_new:
                    self.current_posts.append(new_post_data)
                    messagebox.showinfo(
                        "Éxito", "Post añadido exitosamente a la lista (aún no guardado en JSON).")
                else:
                    self.current_posts[post_index] = new_post_data
                    messagebox.showinfo(
                        "Éxito", "Post actualizado exitosamente en la lista (aún no guardado en JSON).")

                # 5. Refrescar la tabla
                self.populate_post_tree()

                # 6. Cerrar el diálogo
                edit_dialog.destroy()

            except ValueError:
                messagebox.showerror(
                    "Error de Entrada", "Por favor, ingrese solo números enteros válidos para los Delay.")
            except Exception as e:
                messagebox.showerror(
                    "Error", f"Ocurrió un error al guardar el post: {e}")

        # --- Botones del Diálogo ---
        ttb.Button(dialog_frame, text="💾 Aceptar y Actualizar Lista",
                   bootstyle="success", command=save_post_data).pack(pady=(20, 0))
        ttb.Button(dialog_frame, text="Cancelar", bootstyle="secondary",
                   command=edit_dialog.destroy).pack(pady=(5, 0))

        edit_dialog.wait_window(edit_dialog)

    def select_image_file(self, img_var):
        """Abre un diálogo para seleccionar un archivo de imagen o video y actualiza la variable."""
        filepath = filedialog.askopenfilename(
            filetypes=[
                ("Media Files", "*.jpg *.jpeg *.png *.mp4 *.mov"), ("All Files", "*.*")]
        )
        if filepath:
            img_var.set(filepath)

    def delete_selected_post(self):
        """Elimina el post seleccionado de la lista actual (no del JSON hasta guardar)."""
        selected_item = self.post_tree.focus()
        if not selected_item:
            messagebox.showwarning(
                "Advertencia", "Por favor, seleccione un post para eliminar.")
            return

        post_index = int(selected_item)

        respuesta = messagebox.askyesno(
            "Confirmar Eliminación",
            f"¿Está seguro de que desea eliminar el Post #{post_index + 1} de la lista de posts del grupo (requiere guardar cambios)?"
        )

        if respuesta:
            try:
                self.current_posts.pop(post_index)
                self.populate_post_tree()
                messagebox.showinfo(
                    "Éxito", "Post eliminado de la lista. Recuerde hacer clic en 'Guardar Cambios en JSON' para finalizar.")
            except IndexError:
                messagebox.showerror("Error", "Índice de post inválido.")
            except Exception as e:
                messagebox.showerror(
                    "Error", f"Error al eliminar el post: {e}")

    def save_posts_to_group(self, group_name, posts_list, show_success=True):
        """Guarda la lista actual de posts en el archivo JSON del grupo."""
        path = os.path.join(GRUPOS_DIR, f"{group_name}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(posts_list, f, indent=2, ensure_ascii=False)

            # Refrescar la tabla de Grupos en la pestaña principal
            self.update_group_tree()

            if show_success:
                messagebox.showinfo(
                    "Éxito", f"Posts del grupo '{group_name}' guardados exitosamente.")

            return True
        except Exception as e:
            messagebox.showerror("Error al Guardar",
                                 f"Error al guardar {group_name}.json: {e}")
            return False

    def download_group_csv_template(self):
        """Descarga una plantilla CSV para posts de grupo."""

        # Definir la estructura básica del CSV
        header = EXPECTED_POST_KEYS

        # Datos de ejemplo
        data = [
            ["Caption de ejemplo 1 con #hashtags",
                "/ruta/absoluta/a/imagen1.jpg", "30", "60"],
            ["Caption de ejemplo 2 con emojis 🚀",
                "/ruta/absoluta/a/video.mp4", "60", "120"],
        ]

        # Pide al usuario dónde guardar el archivo
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="plantilla_posts.csv"
        )

        if filepath:
            try:
                with open(filepath, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerow(header)
                    writer.writerows(data)
                messagebox.showinfo(
                    "Éxito", f"Plantilla guardada en:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Error al Guardar",
                                     f"Error al guardar el archivo: {e}")

    def import_posts_from_csv(self):
        """Importa posts desde un archivo CSV y crea/actualiza un grupo de posts."""
        filepath = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv")]
        )
        if not filepath:
            return

        group_name = simpledialog.askstring(
            "Nombre del Grupo", "Ingrese el nombre del grupo donde se guardarán estos posts:", parent=self.master)
        if not group_name:
            return

        try:
            new_posts = []

            with open(filepath, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)

                # Verificar las cabeceras requeridas
                if not all(key in reader.fieldnames for key in EXPECTED_POST_KEYS):
                    messagebox.showerror(
                        "Error", f"El CSV debe contener las columnas: {', '.join(EXPECTED_POST_KEYS)}")
                    return

                for row in reader:
                    try:
                        post = {
                            'caption': row.get('caption', '').strip(),
                            'img': row.get('img', '').strip(),
                            'delay_min': int(row.get('delay_min', 30)),
                            'delay_max': int(row.get('delay_max', 60))
                        }

                        # Validación básica
                        if not post['caption'] and not post['img']:
                            print(
                                f"⏩ Saltando fila incompleta (sin caption ni imagen): {row}")
                            continue

                        if post['delay_min'] < 1 or post['delay_max'] < 1 or post['delay_min'] > post['delay_max']:
                            print(
                                f"⚠️ Saltando fila por delay inválido: {row}")
                            continue

                        new_posts.append(post)

                    except ValueError:
                        print(
                            f"⚠️ Saltando fila por valores de delay no numéricos: {row}")
                        continue

            if not new_posts:
                messagebox.showwarning(
                    "Advertencia", "No se encontraron posts válidos en el archivo CSV.")
                return

            if self.save_posts_to_group(group_name, new_posts):
                messagebox.showinfo(
                    "Importación Completa", f"Se importaron {len(new_posts)} posts al grupo '{group_name}'.")

        except FileNotFoundError:
            messagebox.showerror("Error", "Archivo no encontrado.")
        except Exception as e:
            messagebox.showerror("Error de Importación",
                                 f"Ocurrió un error al leer el CSV: {e}")

    # --- Métodos de Diagnóstico ---

    def update_fallos_tree(self):
        """Carga los fallos desde fallos.json (generado por el bot) y actualiza el Treeview."""
        # 1. Limpiar tabla (CRUCIAL para reflejar el estado actual sin duplicados)
        for i in self.fallos_tree.get_children():
            self.fallos_tree.delete(i)
            
        # 2. Cargar datos
        fallos = load_fallos_data() 
        
        # 3. Insertar nuevos fallos
        for fallo in fallos:
            error_msg = fallo.get('error_msg', 'Error Desconocido')
            
            # Limitar el mensaje para que quepa bien en la columna
            display_error_msg = error_msg[:120] + ('...' if len(error_msg) > 120 else '')
            
            self.fallos_tree.insert('', tk.END, values=(
                fallo.get('timestamp', 'N/A'),
                fallo.get('nombre', 'N/A'),
                fallo.get('post', 'N/A'),
                display_error_msg
            ), tags=('error_entry',))

        self.fallos_tree.tag_configure('error_entry', foreground='darkred')

    def sort_treeview(self, tree, col, reverse):
        """Función genérica para ordenar un Treeview por una columna."""
        l = [(tree.set(k, col), k) for k in tree.get_children('')]

        # Lógica de ordenación para la columna Timestamp
        if col == 'Timestamp':
            try:
                l.sort(key=lambda t: datetime.strptime(
                    t[0], "%Y-%m-%d %H:%M:%S"), reverse=reverse)
            except ValueError:
                # Si hay algún error de formato, ordena como string
                l.sort(key=lambda t: t[0], reverse=reverse)
        else:
            l.sort(key=lambda t: t[0], reverse=reverse)

        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)

        # Alternar la dirección de orden
        tree.heading(col, command=lambda:
                     self.sort_treeview(tree, col, not reverse))


# --------------------------------------------------------------------------------------
# Este bloque de funciones (cargar_cuentas, guardar_cuentas, _update_account_state)
# debería estar en core_poster.py o una utilidad compartida. Se mantiene aquí para
# asegurar que la GUI funcione si no está en core_poster, pero se recomienda moverlo.
# --------------------------------------------------------------------------------------

def cargar_cuentas():
    """Carga y retorna los datos de cuentas.json."""
    if os.path.exists(CUENTAS_PATH):
        try:
            with open(CUENTAS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("⚠️ Advertencia: cuentas.json está corrupto. Creando lista vacía.")
            return []
        except Exception:
            return []
    return []


def guardar_cuentas(cuentas):
    """Guarda la lista de cuentas a cuentas.json."""
    try:
        with open(CUENTAS_PATH, 'w', encoding='utf-8') as f:
            json.dump(cuentas, f, indent=2, ensure_ascii=False)
    except Exception as e:
        messagebox.showerror("Error de Guardado",
                             f"No se pudieron guardar las cuentas: {e}")


def _update_account_state(account_name, new_state, reason=None):
    """
    Actualiza el estado de una cuenta en cuentas.json (usado por el bot y la GUI).
    Se usa _update_account_state en la GUI para interactuar con la lógica del core.
    """
    cuentas = cargar_cuentas()
    found = False
    for cuenta in cuentas:
        if cuenta.get('nombre') == account_name:
            cuenta['estado'] = new_state
            if reason:
                if new_state == 'quarantine':
                    cuenta['quarantine_reason'] = reason
                elif new_state == 'bloqueo' or new_state == 'require_login':
                    cuenta['block_reason'] = reason
                else:
                    cuenta.pop('quarantine_reason', None)
                    cuenta.pop('block_reason', None)
            else:
                cuenta.pop('quarantine_reason', None)
                cuenta.pop('block_reason', None)

            found = True
            break

    if found:
        guardar_cuentas(cuentas)
        return True
    return False

# --------------------------------------------------------------------------------------


if __name__ == '__main__':
    root = ttb.Window()
    app = PosterApp(root)
    root.mainloop()
