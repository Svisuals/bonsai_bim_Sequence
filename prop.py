# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

import bpy
from bonsai.bim.module.sequence import helper
import json
import isodate
import ifcopenshell.api
import ifcopenshell.api.sequence
import ifcopenshell.util.attribute
import ifcopenshell.util.date
import bonsai.tool as tool
import bonsai.core.sequence as core
from bonsai.bim.module.sequence.data import SequenceData, AnimationColorSchemeData, refresh as refresh_sequence_data
import bonsai.bim.module.resource.data
import bonsai.bim.module.pset.data
from mathutils import Color
from bonsai.bim.prop import Attribute, ISODuration
from dateutil import parser
from bpy.types import PropertyGroup
from bpy.props import (
    PointerProperty,
    StringProperty,
    EnumProperty,
    BoolProperty,
    IntProperty,
    FloatProperty,
    FloatVectorProperty,
    CollectionProperty,
)
from typing import TYPE_CHECKING, Literal, get_args, Optional, Dict, List, Set


# --- COMIENZO DEL CÓDIGO CORREGIDO ---
def get_operator_items(self, context):
    """
    Genera dinámicamente la lista de operadores según el tipo de dato de la columna seleccionada.
    """
    data_type = getattr(self, 'data_type', 'string')

    common_ops = [
        ('EQUALS', "Equals", "The value is exactly the same"),
        ('NOT_EQUALS', "Does not equal", "The value is different"),
        ('EMPTY', "Is empty", "The field has no value"),
        ('NOT_EMPTY', "Is not empty", "The field has a value"),
    ]

    if data_type in ('integer', 'real', 'float'):
        return [
            ('GREATER', "Greater than", ">"),
            ('LESS', "Less than", "<"),
            ('GTE', "Greater or Equal", ">="),
            ('LTE', "Less or Equal", "<="),
        ] + common_ops
    elif data_type == 'date':
        return [
            ('GREATER', "After Date", "The date is after the specified one"),
            ('LESS', "Before Date", "The date is before the specified one"),
            ('GTE', "On or After Date", "The date is on or after the specified one"),
            ('LTE', "On or Before Date", "The date is on or before the specified one"),
        ] + common_ops
    elif data_type == 'boolean':
        return [
            ('EQUALS', "Is", "The value is true or false"),
            ('NOT_EQUALS', "Is not", "The value is the opposite"),
        ]
    else:  # string, enum, y otros por defecto
        return [
            ('CONTAINS', "Contains", "The text string is contained"),
            ('NOT_CONTAINS', "Does not contain", "The text string is not contained"),
        ] + common_ops

def update_filter_column(self, context):
    """
    Callback que se ejecuta al cambiar la columna del filtro.
    Identifica el tipo de dato y resetea los valores para evitar inconsistencias.
    """
    try:
        # El identificador ahora es 'IfcTask.Name||string'. Extraemos el tipo de dato.
        parts = (self.column or "").split('||')
        if len(parts) == 2:
            self.data_type = parts[1]
        else:
            self.data_type = 'string' # Tipo por defecto seguro

        # Resetear todos los campos de valor para empezar de cero
        self.value_string = ""
        self.value_integer = 0
        self.value_float = 0.0
        self.value_boolean = False
    except Exception as e:
        self.data_type = 'string'
# --- FIN DEL CÓDIGO CORREGIDO ---


def update_task_checkbox_selection(self, context):
    """
    Callback que se ejecuta al marcar/desmarcar un checkbox.
    Utiliza un temporizador para ejecutar la lógica de selección 3D de forma segura.
    """
    def apply_selection():
        try:
            tool.Sequence.apply_selection_from_checkboxes()
        except Exception as e:
            print(f"Error in delayed checkbox selection update: {e}")
        return None  # El temporizador solo se ejecuta una vez

    bpy.app.timers.register(apply_selection, first_interval=0.01)


# ============================================================================
# UNIFIED PROFILE MANAGER - CLASE CENTRAL PARA GESTIONAR PERFILES
# ============================================================================
class UnifiedProfileManager:
    @staticmethod
    def ensure_default_group(context):
        """Asegura que el grupo DEFAULT existe con 13 perfiles predefinidos y propiedades completas."""
        scene = context.scene
        key = "BIM_AppearanceProfileSets"
        raw = scene.get(key, "{}")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        # Crear DEFAULT si no existe
        if "DEFAULT" not in data:
            default_profiles = [
                {"name": "CONSTRUCTION", "start_color": [1,1,1,0], "in_progress_color": [0,1,0,1], "end_color": [0.3,1,0.3,1]},
                {"name": "INSTALLATION", "start_color": [1,1,1,0], "in_progress_color": [0,0.8,0.5,1], "end_color": [0.3,0.8,0.5,1]},
                {"name": "DEMOLITION", "start_color": [1,1,1,1], "in_progress_color": [1,0,0,1], "end_color": [0,0,0,0]},
                {"name": "REMOVAL", "start_color": [1,1,1,1], "in_progress_color": [1,0.3,0,1], "end_color": [0,0,0,0]},
                {"name": "DISPOSAL", "start_color": [1,1,1,1], "in_progress_color": [0.8,0,0.2,1], "end_color": [0,0,0,0]},
                {"name": "DISMANTLE", "start_color": [1,1,1,1], "in_progress_color": [1,0.5,0,1], "end_color": [0,0,0,0]},
                {"name": "OPERATION", "start_color": [1,1,1,1], "in_progress_color": [0,0.5,1,1], "end_color": [1,1,1,1]},
                {"name": "MAINTENANCE", "start_color": [1,1,1,1], "in_progress_color": [0.3,0.6,1,1], "end_color": [1,1,1,1]},
                {"name": "ATTENDANCE", "start_color": [1,1,1,1], "in_progress_color": [0.5,0.5,1,1], "end_color": [1,1,1,1]},
                {"name": "RENOVATION", "start_color": [1,1,1,1], "in_progress_color": [0.5,0,1,1], "end_color": [0.9,0.9,0.9,1]},
                {"name": "LOGISTIC", "start_color": [1,1,1,1], "in_progress_color": [1,1,0,1], "end_color": [1,0.8,0.3,1]},
                {"name": "MOVE", "start_color": [1,1,1,1], "in_progress_color": [1,0.8,0,1], "end_color": [0.8,0.6,0,1]},
                {"name": "NOTDEFINED", "start_color": [0.7,0.7,0.7,1], "in_progress_color": [0.5,0.5,0.5,1], "end_color": [0.3,0.3,0.3,1]},
            ]
            # Rellenar con campos completos
            for profile in default_profiles:
                profile.update({
                    "consider_start": True,
                    "consider_active": True,
                    "consider_end": True,
                    "use_start_original_color": False,
                    "use_active_original_color": False,
                    "use_end_original_color": profile["name"] not in ["DEMOLITION", "REMOVAL", "DISPOSAL", "DISMANTLE"],
                    "start_transparency": 0.0,
                    "active_start_transparency": 0.0,
                    "active_finish_transparency": 0.0,
                    "active_transparency_interpol": 1.0,
                    "end_transparency": 0.0
                })
            data["DEFAULT"] = {"profiles": default_profiles}
            scene[key] = json.dumps(data)
            print("✅ DEFAULT group created with 13 predefined profiles")
        return data
    
    @staticmethod
    def _read_sets_json(context):
        """Lee de forma segura el JSON de perfiles desde la escena."""
        import json
        try:
            scene = context.scene
            key = "BIM_AppearanceProfileSets"
            raw = scene.get(key, "{}")
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _write_sets_json(context, data):
        """Escribe de forma segura el JSON de perfiles en la escena."""
        import json
        try:
            context.scene["BIM_AppearanceProfileSets"] = json.dumps(data)
        except Exception:
            pass

    @staticmethod
    def get_all_predefined_types(context) -> list:
        """Obtiene todos los PredefinedTypes de las tareas cargadas para asegurar que existan perfiles para ellos."""
        try:
            from bonsai.bim.module.sequence.data import SequenceData
            if not SequenceData.is_loaded:
                SequenceData.load()
            
            types = {"NOTDEFINED", "USERDEFINED"} # Siempre incluir estos
            tasks_data = (SequenceData.data or {}).get("tasks", {})
            for task in tasks_data.values():
                if predef_type := task.get("PredefinedType"):
                    types.add(predef_type)
            return sorted(list(types))
        except Exception:
            # Fallback con tipos comunes si falla la lectura
            return [
                "ATTENDANCE", "CONSTRUCTION", "DEMOLITION", "DISMANTLE",
                "DISPOSAL", "INSTALLATION", "LOGISTIC", "MAINTENANCE",
                "MOVE", "OPERATION", "REMOVAL", "RENOVATION", "NOTDEFINED"
            ]

    @staticmethod
    def ensure_profile_in_group(context, group_name: str, profile_name: str):
        """Asegura que un perfil especÃ­fico exista dentro de un grupo en el JSON."""
        if not group_name or not profile_name:
            return
        data = UnifiedProfileManager._read_sets_json(context)
        group = data.setdefault(group_name, {"profiles": []})
        
        # Usa un set para bÃºsqueda rÃ¡pida y evitar duplicados
        existing_profiles = {p.get("name") for p in group.get("profiles", [])}

        if profile_name not in existing_profiles:
            profile_payload = {
                "name": profile_name, "start_color": [1,1,1,0], "in_progress_color": [0,1,0,1], 
                "end_color": [0.7,0.7,0.7,1], "use_end_original_color": True,
                # AÃ±adir todos los campos para consistencia
                "consider_start": True, "consider_active": True, "consider_end": True,
                "use_start_original_color": False, "use_active_original_color": False,
                "start_transparency": 0.0, "active_start_transparency": 0.0, "active_finish_transparency": 0.0,
                "active_transparency_interpol": 1.0, "end_transparency": 0.0
            }
            group["profiles"].append(profile_payload)
            UnifiedProfileManager._write_sets_json(context, data)
            print(f"âœ… Perfil '{profile_name}' aÃ±adido al grupo '{group_name}'.")

    @staticmethod
    def ensure_default_group_has_predefined_types(context):
        """Garantiza que el grupo DEFAULT contenga un perfil para cada PredefinedType existente."""
        all_types = UnifiedProfileManager.get_all_predefined_types(context)
        for p_type in all_types:
            UnifiedProfileManager.ensure_profile_in_group(context, "DEFAULT", p_type)

    @staticmethod
    def sync_default_group_to_predefinedtype(context, task_pg):
        """
        FunciÃ³n clave: Sincroniza la entrada DEFAULT de una tarea con su PredefinedType actual.
        Esta funciÃ³n es la responsable de actualizar el dato que se mostrarÃ¡ en la UI.
        """
        if not task_pg: return
        
        # 1. Obtener el PredefinedType actual de la tarea desde los datos cacheados.
        try:
            from bonsai.bim.module.sequence.data import SequenceData
            tid = getattr(task_pg, "ifc_definition_id", None)
            task_data = (SequenceData.data.get("tasks", {}) or {}).get(tid)
            predef_type = (task_data.get("PredefinedType") or "NOTDEFINED") if task_data else "NOTDEFINED"
        except Exception:
            predef_type = "NOTDEFINED"

        # 2. Asegurarse de que el perfil para este tipo exista en el grupo DEFAULT.
        UnifiedProfileManager.ensure_profile_in_group(context, "DEFAULT", predef_type)

        # 3. Actualizar la entrada 'DEFAULT' en la colecciÃ³n de la tarea.
        try:
            coll = getattr(task_pg, "profile_group_choices", None)
            if coll is None: return

            default_entry = next((item for item in coll if item.group_name == "DEFAULT"), None)

            if not default_entry:
                default_entry = coll.add()
                default_entry.group_name = "DEFAULT"
            
            # 4. Asignar el perfil y asegurarse de que estÃ© habilitado.
            default_entry.selected_profile = predef_type
            default_entry.enabled = True # El grupo DEFAULT siempre estÃ¡ activo.

        except Exception as e:
            print(f"â Œ Error al sincronizar DEFAULT para la tarea: {e}")

    @staticmethod
    def initialize_default_for_all_tasks(context) -> bool:
        """Recorre todas las tareas y asegura que su grupo DEFAULT estÃ© inicializado y sincronizado."""
        try:
            tprops = tool.Sequence.get_task_tree_props()
            if not tprops or not hasattr(tprops, 'tasks'):
                return False
            
            # Asegurar primero que todos los perfiles necesarios existan.
            UnifiedProfileManager.ensure_default_group_has_predefined_types(context)

            for task in tprops.tasks:
                UnifiedProfileManager.sync_default_group_to_predefinedtype(context, task)
            
            print(f"âœ… Sincronizados {len(tprops.tasks)} tareas con el perfil DEFAULT.")
            return True
        except Exception as e:
            print(f"â Œ Error al inicializar perfiles DEFAULT para todas las tareas: {e}")
            return False

    @staticmethod
    def get_user_created_groups(context) -> list:
        """Retorna una lista de nombres de grupos que no son 'DEFAULT'."""
        try:
            all_groups = list(UnifiedProfileManager._read_sets_json(context).keys())
            return sorted([g for g in all_groups if g != "DEFAULT"])
        except Exception:
            return []
            
    # Methods from the original implementation that are still needed and relevant
    @staticmethod
    def validate_profile_data(profile_data: dict) -> bool:
        """Validates the complete data structure of the profile"""
        required_fields = ['name', 'start_color', 'in_progress_color', 'end_color']
        if not all(field in profile_data for field in required_fields):
            return False
    
        # Validate colors
        for color_field in ['start_color', 'in_progress_color', 'end_color']:
            color = profile_data.get(color_field)
            if not isinstance(color, (list, tuple)) or len(color) not in (3, 4):
                return False
    
        # Validate optional values
        optional_floats = [
            'start_transparency', 'active_start_transparency', 
            'active_finish_transparency', 'active_transparency_interpol', 
            'end_transparency'
        ]
        for field in optional_floats:
            if field in profile_data:
                try:
                    val = float(profile_data[field])
                    if not 0.0 <= val <= 1.0:
                        return False
                except (TypeError, ValueError):
                    return False
    
        return True

    @staticmethod
    def get_group_profiles(context, group_name: str) -> Dict[str, dict]:
        """Gets profiles from a specific group"""
        try:
            data = UnifiedProfileManager._read_sets_json(context)
        
            if isinstance(data, dict) and group_name in data:
                profiles = {}
                for profile in data[group_name].get("profiles", []):
                    if UnifiedProfileManager.validate_profile_data(profile):
                        profiles[profile["name"]] = profile
                return profiles
        except Exception:
            pass
        return {}
    
    @staticmethod
    def get_all_groups(context) -> list:
        """Retorna una lista de nombres de todos los grupos."""
        try:
            return sorted(list(UnifiedProfileManager._read_sets_json(context).keys()))
        except Exception:
            return []

    @staticmethod
    def get_profiles_from_specific_group(context, group_name: str) -> list:
        """Get profile names from a specific group (para usar en enums)"""
        try:
            profiles_data = UnifiedProfileManager.get_group_profiles(context, group_name)
            return sorted(list(profiles_data.keys()))
        except Exception as e:
            print(f"â Œ Error getting profiles from group '{group_name}': {e}")
            return []

    @staticmethod
    def debug_profile_state(context, task_id: int = None):
        """Debug helper para mostrar estado de perfiles"""
        try:
            print("=== PROFILE DEBUG STATE ===")
            
            # Mostrar todos los grupos
            all_groups = UnifiedProfileManager.get_all_groups(context)
            user_groups = UnifiedProfileManager.get_user_created_groups(context)
            print(f"All groups: {all_groups}")
            print(f"User groups (no DEFAULT): {user_groups}")
            
            # Mostrar props de animaciÃ³n
            try:
                anim_props = tool.Sequence.get_animation_props()
                print(f"Active profile_groups: {getattr(anim_props, 'profile_groups', 'N/A')}")
                print(f"Task profile selector: {getattr(anim_props, 'task_profile_group_selector', 'N/A')}")
                print(f"Loaded profiles count: {len(getattr(anim_props, 'profiles', []))}")
                
                for i, p in enumerate(getattr(anim_props, 'profiles', [])):
                    print(f"  [{i}] {getattr(p, 'name', 'NO_NAME')}")
            except Exception as e:
                print(f"Error getting anim props: {e}")
            
            # Mostrar datos de tarea especÃ­fica
            if task_id:
                try:
                    tprops = tool.Sequence.get_task_tree_props()
                    wprops = tool.Sequence.get_work_schedule_props()
                    if tprops.tasks and wprops.active_task_index < len(tprops.tasks):
                        task = tprops.tasks[wprops.active_task_index]
                        print(f"Task {task.ifc_definition_id} profile mappings:")
                        for choice in getattr(task, 'profile_group_choices', []):
                            print(f"  {choice.group_name} -> {choice.selected_profile} (enabled: {choice.enabled})")
                        print(f"  use_active_profile_group: {getattr(task, 'use_active_profile_group', 'N/A')}")
                        print(f"  selected_profile_in_active_group: {getattr(task, 'selected_profile_in_active_group', 'N/A')}")
                except Exception as e:
                    print(f"Error getting task data: {e}")
            
            print("=== END DEBUG ===")
        except Exception as e:
            print(f"â Œ Debug failed: {e}")


    @staticmethod
    def sync_task_profiles(context, task, group_name: str):
        """Synchronizes task profiles with the active group - eliminates duplication"""
        valid_profiles = UnifiedProfileManager.get_group_profiles(context, group_name)
    
        if hasattr(task, 'profile_group_choices'):
            # Find or create an entry for the group
            entry = None
            for choice in task.profile_group_choices:
                if choice.group_name == group_name:
                    entry = choice
                    break
        
            if not entry:
                entry = task.profile_group_choices.add()
                entry.group_name = group_name
                entry.enabled = False
                entry.selected_profile = ""
        
            # Validate selected profile
            if entry.selected_profile and entry.selected_profile not in valid_profiles:
                entry.selected_profile = ""
        
            return entry
        return None

    @staticmethod
    def cleanup_invalid_mappings(context):
        """Cleans up all invalid profile mappings"""
        valid_groups = set(UnifiedProfileManager._read_sets_json(context).keys())
    
        try:
            tprops = tool.Sequence.get_task_tree_props()
            for task in getattr(tprops, "tasks", []):
                if hasattr(task, 'profile_group_choices'):
                    # Collect indices to remove
                    to_remove = []
                    for idx, choice in enumerate(task.profile_group_choices):
                        if choice.group_name not in valid_groups:
                            to_remove.append(idx)
                        else:
                            # Validate profile within the group
                            profiles = UnifiedProfileManager.get_group_profiles(context, choice.group_name)
                            if choice.selected_profile and choice.selected_profile not in profiles:
                                choice.selected_profile = ""
                
                    # Remove invalid entries
                    for offset, idx in enumerate(to_remove):
                        task.profile_group_choices.remove(idx - offset)
        except Exception as e:
            print(f"Error cleaning invalid mappings: {e}")

    @staticmethod
    def load_profiles_into_collection(props, context, group_name: str):
        """Loads profiles from a group into the property collection"""
        profiles_data = UnifiedProfileManager.get_group_profiles(context, group_name)
    
        try:
            props.profiles.clear()
            for profile_name, profile_data in profiles_data.items():
                p = props.profiles.add()
                p.name = profile_name
            
                # Colors
                for attr in ("start_color", "in_progress_color", "end_color"):
                    col = profile_data.get(attr, [1, 1, 1, 1])
                    if isinstance(col, (list, tuple)):
                        rgba = list(col) + [1.0] * (4 - len(col))
                        setattr(p, attr, rgba[:4])
            
                # Booleans
                for attr in ("use_start_original_color", "use_active_original_color", "use_end_original_color"):
                    if attr in profile_data:
                        setattr(p, attr, bool(profile_data[attr]))
            
                # Transparencies
                for attr in ("active_start_transparency", "active_finish_transparency", 
                           "active_transparency_interpol", "start_transparency", "end_transparency"):
                    if attr in profile_data:
                        try:
                            setattr(p, attr, float(profile_data[attr]))
                        except Exception:
                            pass
        
            if props.profiles:
                props.active_profile_index = 0
        except Exception as e:
            print(f"Error loading profiles: {e}")

# ============================================================================
# CALLBACK FUNCTIONS - Improved with the new system
# ============================================================================

def getTaskColumns(self, context):
    if not SequenceData.is_loaded:
        SequenceData.load()
    return SequenceData.data["task_columns_enum"]


def getTaskTimeColumns(self, context):
    if not SequenceData.is_loaded:
        SequenceData.load()
    return SequenceData.data["task_time_columns_enum"]


def getWorkSchedules(self, context):
    if not SequenceData.is_loaded:
        SequenceData.load()
    return SequenceData.data["work_schedules_enum"]


def getWorkCalendars(self, context):
    if not SequenceData.is_loaded:
        SequenceData.load()
    return SequenceData.data["work_calendars_enum"]


def get_appearance_profile_items(self, context):
    """Gets profile items for dropdown"""
    props = tool.Sequence.get_animation_props()
    items = []
    try:
        for i, p in enumerate(props.profiles):
            name = p.name or f"Profile {i+1}"
            items.append((name, name, "", i))
    except Exception:
        pass
    if not items:
        items = [("", "<no profiles>", "", 0)]
    return items


def get_custom_group_profile_items(self, context):
    """
    Gets profile items ONLY from the selected custom group (excludes DEFAULT).
    This version reads directly from the JSON and is more lenient to allow UI selection
    even if profile data is incomplete.
    """
    items = []
    try:
        anim_props = tool.Sequence.get_animation_props()
        selected_group = getattr(anim_props, "task_profile_group_selector", "")
        
        if selected_group and selected_group != "DEFAULT":
            # Lectura directa y flexible desde el JSON
            all_sets = UnifiedProfileManager._read_sets_json(context)
            group_data = all_sets.get(selected_group, {})
            profiles_list = group_data.get("profiles", [])
            
            profile_names = []
            for profile in profiles_list:
                if isinstance(profile, dict) and "name" in profile:
                    profile_names.append(profile["name"])
            
            for i, name in enumerate(sorted(profile_names)):
                items.append((name, name, f"Profile from {selected_group}", i))
    
    except Exception as e:
        print(f"Error getting custom group profiles: {e}")
        items.append(("", "<error loading profiles>", "", 0))

    if not items:
        anim_props = tool.Sequence.get_animation_props()
        selected_group = getattr(anim_props, "task_profile_group_selector", "")
        if not selected_group:
            items.append(("", "<select custom group first>", "", 0))
        elif selected_group == "DEFAULT":
            items.append(("", "<DEFAULT not allowed here>", "", 0))
        else:
            items.append(("", f"<no profiles in {selected_group}>", "", 0))
            
    return items

def update_active_task_index(self, context):
    """
    Updates active task index, synchronizes profiles,
    and selects associated 3D objects in the viewport (for single click).
    """
    task_ifc = tool.Sequence.get_highlighted_task()
    self.highlighted_task_id = task_ifc.id() if task_ifc else 0
    tool.Sequence.update_task_ICOM(task_ifc)
    bonsai.bim.module.pset.data.refresh()

    if self.editing_task_type == "SEQUENCE":
        tool.Sequence.load_task_properties()

    try:
        tprops = tool.Sequence.get_task_tree_props()
        if tprops.tasks and self.active_task_index < len(tprops.tasks):
            task_pg = tprops.tasks[self.active_task_index]
            if 'UnifiedProfileManager' in globals() and UnifiedProfileManager:
                UnifiedProfileManager.sync_default_group_to_predefinedtype(context, task_pg)
                anim_props = tool.Sequence.get_animation_props()
                if anim_props.profile_groups:
                    UnifiedProfileManager.sync_task_profiles(context, task_pg, anim_props.profile_groups)
    except Exception as e:
        print(f"[ERROR] Error syncing profiles in update_active_task_index: {e}")

    # --- COMIENZO DEL CÓDIGO CORREGIDO ---
    # --- LÓGICA DE SELECCIÓN 3D PARA CLIC INDIVIDUAL ---
    if not task_ifc:
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except RuntimeError:
            # Ocurre si no estamos en modo objeto, es seguro ignorarlo.
            pass
        return

    try:
        outputs = tool.Sequence.get_task_outputs(task_ifc)
        
        # Deseleccionar todo lo demás primero
        if bpy.context.view_layer.objects.active:
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')

        if outputs:
            objects_to_select = [tool.Ifc.get_object(p) for p in outputs if tool.Ifc.get_object(p)]
            
            if objects_to_select:
                for obj in objects_to_select:
                    # <-- PASO 1: Asegurarse de que el objeto sea visible y seleccionable
                    obj.hide_set(False)
                    obj.hide_select = False
                    
                    # <-- PASO 2: Seleccionar el objeto
                    obj.select_set(True)
                
                # <-- PASO 3: Establecer el primer objeto como activo
                context.view_layer.objects.active = objects_to_select[0]
                
                # <-- PASO 4: Centrar la vista 3D en los objetos seleccionados
                bpy.ops.view3d.view_selected()
                
    except Exception as e:
        print(f"Error selecting 3D objects for task: {e}")
    # --- FIN DEL CÓDIGO CORREGIDO ---

    items = []
    try:
        anim_props = tool.Sequence.get_animation_props()
        selected_group = getattr(anim_props, "task_profile_group_selector", "")
        
        print(f"ðŸ”  Getting profiles for custom group: '{selected_group}'")
        
        # CRÃ TICO: Solo mostrar perfiles si hay un grupo personalizado seleccionado
        if selected_group and selected_group != "DEFAULT":
            from bonsai.bim.module.sequence.prop import UnifiedProfileManager
            profiles = UnifiedProfileManager.get_group_profiles(context, selected_group)
            
            for i, name in enumerate(sorted(profiles.keys())):
                items.append((name, name, f"Profile from {selected_group}", i))
            
            print(f"âœ… Found {len(items)} profiles in group '{selected_group}'")

    except Exception as e:
        print(f"â Œ Error getting custom group profiles: {e}")
        items = [("", "<error loading profiles>", "", 0)]

    if not items:
        anim_props = tool.Sequence.get_animation_props()
        selected_group = getattr(anim_props, "task_profile_group_selector", "")
        if not selected_group:
            items = [("", "<select custom group first>", "", 0)]
        elif selected_group == "DEFAULT":
            items = [("", "<DEFAULT not allowed here>", "", 0)]
        else:
            items = [("", f"<no profiles in {selected_group}>", "", 0)]
            
    return items


def update_active_task_outputs(self, context):
    task = tool.Sequence.get_highlighted_task()
    outputs = tool.Sequence.get_task_outputs(task)
    tool.Sequence.load_task_outputs(outputs)


def update_active_task_resources(self, context):
    task = tool.Sequence.get_highlighted_task()
    resources = tool.Sequence.get_task_resources(task)
    tool.Sequence.load_task_resources(resources)


def update_active_task_inputs(self, context):
    task = tool.Sequence.get_highlighted_task()
    inputs = tool.Sequence.get_task_inputs(task)
    tool.Sequence.load_task_inputs(inputs)


def updateTaskName(self: "Task", context: bpy.types.Context) -> None:
    props = tool.Sequence.get_work_schedule_props()
    if not props.is_task_update_enabled or self.name == "Unnamed":
        return
    ifc_file = tool.Ifc.get()
    ifcopenshell.api.sequence.edit_task(
        ifc_file,
        task=ifc_file.by_id(self.ifc_definition_id),
        attributes={"Name": self.name},
    )
    SequenceData.load()
    if props.active_task_id == self.ifc_definition_id:
        attribute = props.task_attributes["Name"]
        attribute.string_value = self.name


def updateTaskIdentification(self: "Task", context: bpy.types.Context) -> None:
    props = tool.Sequence.get_work_schedule_props()
    if not props.is_task_update_enabled or self.identification == "XXX":
        return
    ifc_file = tool.Ifc.get()
    ifcopenshell.api.sequence.edit_task(
        ifc_file,
        task=ifc_file.by_id(self.ifc_definition_id),
        attributes={"Identification": self.identification},
    )
    SequenceData.load()
    if props.active_task_id == self.ifc_definition_id:
        attribute = props.task_attributes["Identification"]
        attribute.string_value = self.identification


def updateTaskTimeStart(self: "Task", context: bpy.types.Context) -> None:
    updateTaskTimeDateTime(self, context, "start")


def updateTaskTimeFinish(self: "Task", context: bpy.types.Context) -> None:
    updateTaskTimeDateTime(self, context, "finish")


def updateTaskTimeDateTime(self: "Task", context: bpy.types.Context, startfinish: Literal["start", "finish"]) -> None:
    props = tool.Sequence.get_work_schedule_props()

    if not props.is_task_update_enabled:
        return

    def canonicalise_time(time):
        if not time:
            return "-"
        return time.strftime("%Y-%m-%d")

    startfinish_value = getattr(self, startfinish)

    if startfinish_value == "-":
        return

    ifc_file = tool.Ifc.get()

    try:
        startfinish_datetime = parser.isoparse(startfinish_value)
    except:
        try:
            startfinish_datetime = parser.parse(startfinish_value, dayfirst=True, fuzzy=True)
        except:
            setattr(self, startfinish, "-")
            return

    task = ifc_file.by_id(self.ifc_definition_id)
    if task.TaskTime:
        task_time = task.TaskTime
    else:
        task_time = ifcopenshell.api.sequence.add_task_time(ifc_file, task=task)
        SequenceData.load()

    startfinish_key = "Schedule" + startfinish.capitalize()
    if SequenceData.data["task_times"][task_time.id()][startfinish_key] == startfinish_datetime:
        canonical_startfinish_value = canonicalise_time(startfinish_datetime)
        if startfinish_value != canonical_startfinish_value:
            setattr(self, startfinish, canonical_startfinish_value)
        return

    ifcopenshell.api.sequence.edit_task_time(
        ifc_file,
        task_time=task_time,
        attributes={startfinish_key: startfinish_datetime},
    )
    SequenceData.load()
    bpy.ops.bim.load_task_properties()


def updateTaskDuration(self: "Task", context: bpy.types.Context) -> None:
    props = tool.Sequence.get_work_schedule_props()
    if not props.is_task_update_enabled:
        return

    if self.duration == "-":
        return

    duration = ifcopenshell.util.date.parse_duration(self.duration)
    if not duration:
        self.duration = "-"
        return

    ifc_file = tool.Ifc.get()
    task = ifc_file.by_id(self.ifc_definition_id)
    if task.TaskTime:
        task_time = task.TaskTime
    else:
        task_time = ifcopenshell.api.sequence.add_task_time(ifc_file, task=task)
    ifcopenshell.api.sequence.edit_task_time(
        ifc_file,
        task_time=task_time,
        attributes={"ScheduleDuration": duration},
    )
    core.load_task_properties(tool.Sequence)
    tool.Sequence.refresh_task_resources()


def updateTaskPredefinedType(self: "Task", context: bpy.types.Context) -> None:
    """Callback when PredefinedType changes - auto-syncs to DEFAULT group"""
    props = tool.Sequence.get_work_schedule_props()
    if not props.is_task_update_enabled:
        return
    try:
        # The primary action of editing the IFC attribute is handled by the Attribute's own update callback.
        # This function's role is to ensure the UI/profile data stays in sync.
        
        # 1. Get the new value from the UI properties
        new_predefined_type = "NOTDEFINED"
        for attr in props.task_attributes:
            if attr.name == "PredefinedType":
                new_predefined_type = attr.get_value() or "NOTDEFINED"
                break
        
        # 2. Auto-sync the task's DEFAULT profile choice to this new type
        UnifiedProfileManager.sync_default_group_to_predefinedtype(context, self)

        print(f"[AUTO-SYNC] Task {self.ifc_definition_id}: PredefinedType changed, DEFAULT profile synced to '{new_predefined_type}'.")
    except Exception as e:
        print(f"[ERROR] updateTaskPredefinedType: {e}")


def get_schedule_predefined_types(self, context):
    if not SequenceData.is_loaded:
        SequenceData.load()
    return SequenceData.data["schedule_predefined_types_enum"]


def update_visualisation_start(self: "BIMWorkScheduleProperties", context: bpy.types.Context) -> None:
    update_visualisation_start_finish(self, context, "visualisation_start")


def update_visualisation_finish(self: "BIMWorkScheduleProperties", context: bpy.types.Context) -> None:
    update_visualisation_start_finish(self, context, "visualisation_finish")


def update_visualisation_start_finish(
    self: "BIMWorkScheduleProperties",
    context: bpy.types.Context,
    startfinish: Literal["visualisation_start", "visualisation_finish"],
) -> None:
    def canonicalise_datetime(dt):
        if not dt:
            return "-"
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    startfinish_value = getattr(self, startfinish)
    try:
        startfinish_datetime = parser.isoparse(startfinish_value)
    except Exception:
        try:
            startfinish_datetime = parser.parse(startfinish_value, dayfirst=True, fuzzy=True)
        except Exception:
            setattr(self, startfinish, "-")
            return

    canonical_value = canonicalise_datetime(startfinish_datetime)
    if startfinish_value != canonical_value:
        setattr(self, startfinish, canonical_value)


def update_color_full(self, context):
    """Updates full bar color"""
    material = bpy.data.materials.get("color_full")
    if material:
        props = tool.Sequence.get_animation_props()
        inputs = tool.Blender.get_material_node(material, "BSDF_PRINCIPLED").inputs
        color = inputs["Base Color"].default_value
        color[0] = props.color_full[0]
        color[1] = props.color_full[1]
        color[2] = props.color_full[2]
        try:
            inputs["Alpha"].default_value = (props.color_full[3] if len(props.color_full) > 3 else 1.0)
            material.blend_method = 'BLEND'
            material.shadow_method = 'HASHED'
        except Exception:
            pass


def update_color_progress(self, context):
    """Updates progress bar color"""
    material = bpy.data.materials.get("color_progress")
    if material:
        props = tool.Sequence.get_animation_props()
        inputs = tool.Blender.get_material_node(material, "BSDF_PRINCIPLED").inputs
        color = inputs["Base Color"].default_value
        color[0] = props.color_progress[0]
        color[1] = props.color_progress[1]
        color[2] = props.color_progress[2]
        try:
            inputs["Alpha"].default_value = (props.color_progress[3] if len(props.color_progress) > 3 else 1.0)
            material.blend_method = 'BLEND'
            material.shadow_method = 'HASHED'
        except Exception:
            pass


def update_sort_reversed(self: "BIMWorkScheduleProperties", context: bpy.types.Context) -> None:
    if self.active_work_schedule_id:
        core.load_task_tree(
            tool.Sequence,
            work_schedule=tool.Ifc.get().by_id(self.active_work_schedule_id),
        )


def update_filter_by_active_schedule(self: "BIMWorkScheduleProperties", context: bpy.types.Context) -> None:
    if obj := context.active_object:
        product = tool.Ifc.get_entity(obj)
        assert product
        core.load_product_related_tasks(tool.Sequence, product=product)


def switch_options(self, context):
    """Toggles between visualization and snapshot"""
    if self.should_show_visualisation_ui:
        self.should_show_snapshot_ui = False
    else:
        if not self.should_show_snapshot_ui:
            self.should_show_snapshot_ui = True


def switch_options2(self, context):
    """Toggles between snapshot and visualization"""
    if self.should_show_snapshot_ui:
        self.should_show_visualisation_ui = False
    else:
        if not self.should_show_visualisation_ui:
            self.should_show_visualisation_ui = True


def get_saved_color_schemes(self, context):
    """Gets saved color schemes (legacy - maintain for compatibility)"""
    if not AnimationColorSchemeData.is_loaded:
        AnimationColorSchemeData.load()
    return AnimationColorSchemeData.data.get("saved_color_schemes", [])


def get_internal_profile_sets_enum(self, context):
    """Gets enum of ALL available profile groups, including DEFAULT."""
    from bonsai.bim.module.sequence.prop import UnifiedProfileManager
    try:
        # Get all groups directly from the source
        all_groups = sorted(list(UnifiedProfileManager._read_sets_json(context).keys()))
        
        if all_groups:
            # Ensure "DEFAULT" appears first for convenience
            if "DEFAULT" in all_groups:
                all_groups.remove("DEFAULT")
                all_groups.insert(0, "DEFAULT")
            return [(name, name, f"Profile group: {name}") for name in all_groups]
    except Exception:
        pass
    
    # Fallback if no groups are found
    return [("", "<no profile groups>", "Create or load profile groups")]



def get_all_groups_enum(self, context):
    """Enum para todos los grupos (incluyendo DEFAULT)."""
    try:
        groups = UnifiedProfileManager.get_all_groups(context)
        items = []
        for i, group in enumerate(sorted(groups)):
            desc = "Auto-managed profiles by PredefinedType" if group == "DEFAULT" else "Custom profile group"
            items.append((group, group, desc, i))
        return items if items else [("DEFAULT", "DEFAULT", "Auto-managed default group", 0)]
    except Exception:
        return [("DEFAULT", "DEFAULT", "Auto-managed default group", 0)]


def get_user_created_groups_enum(self, context):
    """Returns EnumProperty items for user-created groups, excluding 'DEFAULT'."""
    from bonsai.bim.module.sequence.prop import UnifiedProfileManager
    try:
        user_groups = UnifiedProfileManager.get_user_created_groups(context)
        if user_groups:
            return [(name, name, f"Profile group: {name}") for name in user_groups]
    except Exception:
        pass
    return [("", "<no custom groups>", "Create custom groups in the Appearance Profiles panel")]


def update_task_profile_group_selector(self, context):
    """Update when custom group selector changes - ensures profiles are loaded"""
    try:
        # 'self' is BIMAnimationProperties
        if self.task_profile_group_selector and self.task_profile_group_selector != "":
            print(f"ðŸ”„ Custom group selected: {self.task_profile_group_selector}")
            
            # Cargar perfiles de este grupo en la UI para que estÃ©n disponibles
            from bonsai.bim.module.sequence.prop import UnifiedProfileManager
            UnifiedProfileManager.load_profiles_into_collection(self, context, self.task_profile_group_selector)
            
            # NO cambiar profile_groups aquÃ­ - mantenerlo separado para ediciÃ³n
            # self.profile_groups = self.task_profile_group_selector # â†  COMENTAR ESTA LÃ NEA
            
            # Actualizar enum para refrescar dropdown de perfiles
            try:
                tprops = tool.Sequence.get_task_tree_props()
                wprops = tool.Sequence.get_work_schedule_props()
                if tprops.tasks and wprops.active_task_index < len(tprops.tasks):
                    task = tprops.tasks[wprops.active_task_index]
                    # Forzar actualizaciÃ³n del enum
                    task.selected_profile_in_active_group = task.selected_profile_in_active_group
            except Exception:
                pass

    except Exception as e:
        print(f"â Œ Error in update_task_profile_group_selector: {e}")


def monitor_predefined_type_change(context):
    """Monitors changes in PredefinedType and auto-syncs DEFAULT"""
    try:
        tprops = tool.Sequence.get_task_tree_props()
        wprops = tool.Sequence.get_work_schedule_props()

        if not (tprops.tasks and wprops.active_task_index < len(tprops.tasks)):
            return

        task_pg = tprops.tasks[wprops.active_task_index]
        UnifiedProfileManager.sync_default_group_to_predefinedtype(context, task_pg)

    except Exception as e:
        print(f"[ERROR] monitor_predefined_type_change: {e}")


def update_profile_group(self, context):
    """Updates active profile group - Improved with the new system"""
    # Sync to JSON first
    try:
        tool.Sequence.sync_active_group_to_json()
    except Exception as e:
        print(f"Error syncing profiles on group change: {e}")

    # Clean up invalid mappings
    UnifiedProfileManager.cleanup_invalid_mappings(context)

    # Load profiles of the selected group
    if self.profile_groups:
        UnifiedProfileManager.load_profiles_into_collection(self, context, self.profile_groups)

    # Synchronize active task if it exists
    try:
        tprops = tool.Sequence.get_task_tree_props()
        wprops = tool.Sequence.get_work_schedule_props()
        if tprops.tasks and wprops.active_task_index < len(tprops.tasks):
            task = tprops.tasks[wprops.active_task_index]

            # Sync the active custom group profile
            entry = UnifiedProfileManager.sync_task_profiles(context, task, self.profile_groups)
            if entry and hasattr(task, 'selected_profile_in_active_group'):
                task.selected_profile_in_active_group = entry.selected_profile or ""
    except Exception as e:
        print(f"[ERROR] Error in update_profile_group: {e}")


def updateAssignedResourceName(self, context):
    pass


def updateAssignedResourceUsage(self: "TaskResource", context: object) -> None:
    props = tool.Resource.get_resource_props()
    if not props.is_resource_update_enabled:
        return
    if not self.schedule_usage:
        return
    resource = tool.Ifc.get().by_id(self.ifc_definition_id)
    if resource.Usage and resource.Usage.ScheduleUsage == self.schedule_usage:
        return
    tool.Resource.run_edit_resource_time(resource, attributes={"ScheduleUsage": self.schedule_usage})
    tool.Sequence.load_task_properties()
    tool.Resource.load_resource_properties()
    tool.Sequence.refresh_task_resources()
    bonsai.bim.module.resource.data.refresh()
    refresh_sequence_data()
    bonsai.bim.module.pset.data.refresh()



def update_task_bar_list(self: "Task", context: bpy.types.Context) -> None:
    props = tool.Sequence.get_work_schedule_props()
    if not props.is_task_update_enabled:
        return
    
    # Agregar o remover de la lista
    if self.has_bar_visual:
        tool.Sequence.add_task_bar(self.ifc_definition_id)
    else:
        tool.Sequence.remove_task_bar(self.ifc_definition_id)
    
    # Actualizar visualización inmediatamente
    try:
        tool.Sequence.refresh_task_bars()
    except Exception as e:
        print(f"⚠️ Error refreshing task bars: {e}")



def update_use_active_profile_group(self: "Task", context):
    """Updates usage of the active profile group"""
    try:
        anim_props = tool.Sequence.get_animation_props()
        selected_group = getattr(anim_props, "task_profile_group_selector", "")
        
        # CRÃ TICO: Usar el grupo seleccionado en task_profile_group_selector, NO profile_groups
        if selected_group and selected_group != "DEFAULT":
            entry = UnifiedProfileManager.sync_task_profiles(context, self, selected_group)
            if entry:
                entry.enabled = bool(self.use_active_profile_group)
                print(f"ðŸ”„ Task {self.ifc_definition_id}: Group {selected_group} enabled = {entry.enabled}")
    except Exception as e:
        print(f"â Œ Error updating use_active_profile_group: {e}")


def update_selected_profile_in_active_group(self: "Task", context):
    """Updates the selected profile in the active group"""
    try:
        anim_props = tool.Sequence.get_animation_props()
        selected_group = getattr(anim_props, "task_profile_group_selector", "")
        
        # CRÃ TICO: Usar el grupo seleccionado en task_profile_group_selector, NO profile_groups
        if selected_group and selected_group != "DEFAULT":
            entry = UnifiedProfileManager.sync_task_profiles(context, self, selected_group)
            if entry:
                entry.selected_profile = self.selected_profile_in_active_group
                print(f"ðŸ”„ Task {self.ifc_definition_id}: Selected profile = {entry.selected_profile} in group {selected_group}")
    except Exception as e:
        print(f"â Œ Error updating selected_profile_in_active_group: {e}")


# ============================================================================
# PROPERTY GROUPS
# ============================================================================

# === Helper invoked by operator.py (safe no-op if nothing to clean) ==========================
def cleanup_all_tasks_profile_mappings(context):
    """
    Best-effort cleanup to keep taskâ†’profile mappings consistent.
    This is intentionally resilient: if the data structure isn't present or differs
    between Bonsai versions, it silently returns.
    """
    try:
        # Reuse our UPM persistence hooks; if no data, nothing to do
        data = UnifiedProfileManager._read_sets_json(context)
        if not isinstance(data, dict):
            return
        # Optionally prune obviously empty groups/entries if they appear as None/[]
        for gkey, gval in list(data.items()):
            if gval is None or gval == {}:
                del data[gkey]
                continue
            if isinstance(gval, dict):
                for pkey, plist in list(gval.items()):
                    if plist in (None, [], {}, "null"):
                        del gval[pkey]
        UnifiedProfileManager._write_sets_json(context, data)
    except Exception:
        # Do not raise; operators call this after user actions and must not crash
        pass


# === HUD CALLBACKS (GPU-based) ====================================
def toggle_hud_gpu(self, context):
    """Callback para activar/desactivar HUD GPU automáticamente"""
    try:
        if getattr(self, "enable_text_hud", False):
            # Activar HUD GPU
            def enable_hud():
                try:
                    bpy.ops.bim.enable_schedule_hud()
                except Exception as e:
                    print(f"Auto-enable HUD failed: {e}")
            bpy.app.timers.register(enable_hud, first_interval=0.1)
        else:
            # Desactivar HUD GPU
            def disable_hud():
                try:
                    bpy.ops.bim.disable_schedule_hud()
                except Exception as e:
                    print(f"Auto-disable HUD failed: {e}")
            bpy.app.timers.register(disable_hud, first_interval=0.05)
    except Exception as e:
        print(f"HUD GPU toggle callback error: {e}")


def update_hud_gpu(self, context):
    """Callback para actualizar HUD GPU"""
    try:
        if getattr(self, "enable_text_hud", False):
            def refresh_hud():
                try:
                    bpy.ops.bim.refresh_schedule_hud()
                except Exception:
                    pass
            bpy.app.timers.register(refresh_hud, first_interval=0.05)
    except Exception:
        pass


def force_hud_refresh(self, context):
    """Callback mejorado que fuerza actualización del HUD con delay"""
    try:
        def delayed_refresh():
            try:
                bpy.ops.bim.refresh_schedule_hud()
                # Forzar redraw de viewports 3D
                for area in bpy.context.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            except Exception as e:
                print(f"⚠️ Delayed HUD refresh failed: {e}")
            return None  # No repetir
        
        # Registrar timer para actualización retrasada
        bpy.app.timers.register(delayed_refresh, first_interval=0.1)
        
    except Exception as e:
        print(f"❌ Force HUD refresh failed: {e}")

# === END HUD CALLBACKS (GPU) ================================================

# === Camera & Orbit Properties - Definición estática ===

def toggle_3d_text_visibility(self, context):
    """Muestra/oculta la colección de textos 3D con mejor manejo de errores"""
    try:
        collection = bpy.data.collections.get("Schedule_Display_Texts")
        if collection:
            # Forzar actualización del viewport
            collection.hide_viewport = not self.show_3d_schedule_texts
            collection.hide_render = not self.show_3d_schedule_texts
            
            # Forzar refresco de todas las áreas 3D
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        else:
            print("⚠️ Collection 'Schedule_Display_Texts' not found")
    except Exception as e:
        print(f"❌ Error toggling 3D text visibility: {e}")

# --- COMIENZO DEL CÓDIGO CORREGIDO ---
def get_all_task_columns_enum(self, context):
    """
    Genera una lista EnumProperty con TODAS las columnas filtrables,
    incluyendo el tipo de dato en el identificador para uso interno.
    """
    if not SequenceData.is_loaded:
        SequenceData.load()

    items = []
    # 1. Columnas especiales (definidas manualmente)
    # El formato es: "NombreInterno||tipo_de_dato", "Etiqueta UI", "Descripción"
    items.append(("Special.OutputsCount||integer", "Outputs 3D", "Number of elements assigned as task outputs."))

    # 2. Columnas de IfcTask
    for name_type, label, desc in SequenceData.data.get("task_columns_enum", []):
        try:
            name, data_type = name_type.split('/')
            identifier = f"IfcTask.{name}||{data_type}"
            items.append((identifier, f"Task: {label}", desc))
        except Exception:
            continue

    # 3. Columnas de IfcTaskTime
    for name_type, label, desc in SequenceData.data.get("task_time_columns_enum", []):
        try:
            name, data_type = name_type.split('/')
            # Corregimos para que las fechas se traten como 'date'
            final_data_type = 'date' if any(s in label.lower() for s in ['date', 'start', 'finish']) else data_type
            identifier = f"IfcTaskTime.{name}||{final_data_type}"
            items.append((identifier, f"Time: {label}", desc))
        except Exception:
            continue

    return sorted(items, key=lambda x: x[1])
# --- FIN DEL CÓDIGO CORREGIDO ---


class BIMCameraOrbitProperties(PropertyGroup):
    # =====================
    # Camera settings
    # =====================
    camera_focal_mm: FloatProperty(
        name="Focal (mm)",
        default=35.0,
        min=1.0,
        max=300.0,
        description="Camera focal length in millimeters",
    )
    camera_clip_start: FloatProperty(
        name="Clip Start",
        default=0.1,
        min=0.0001,
        description="Camera near clipping distance",
    )
    camera_clip_end: FloatProperty(
        name="Clip End",
        default=10000.0,
        min=1.0,
        description="Camera far clipping distance",
    )

    # =====================
    # Orbit settings
    # =====================
    orbit_mode: EnumProperty(
        name="Orbit Mode",
        items=[
            ("NONE", "None (Static)", "The camera will not move or be animated."),
            ("CIRCLE_360", "Circle 360°", "The camera performs a full 360-degree circular orbit."),
            ("PINGPONG", "Ping-Pong", "The camera moves back and forth along a 180-degree arc."),
        ],
        default="CIRCLE_360",
    )
    orbit_radius_mode: EnumProperty(
        name="Radius Mode",
        items=[
            ("AUTO", "Auto (from bbox)", "Compute radius from WorkSchedule bbox"),
            ("MANUAL", "Manual", "Use manual radius value"),
        ],
        default="AUTO",
    )
    orbit_radius: FloatProperty(
        name="Radius (m)",
        default=10.0,
        min=0.01,
        description="Manual orbit radius in meters",
    )
    orbit_height: FloatProperty(
        name="Height (Z offset)",
        default=8.0,
        description="Height offset from target center",
    )
    orbit_start_angle_deg: FloatProperty(
        name="Start Angle (deg)",
        default=0.0,
        description="Starting angle in degrees",
    )
    orbit_direction: EnumProperty(
        name="Direction",
        items=[("CCW", "CCW", "Counter-clockwise"), ("CW", "CW", "Clockwise")],
        default="CCW",
    )

    # =====================
    # Look At settings
    # =====================
    look_at_mode: EnumProperty(
        name="Look At",
        items=[
            ("AUTO", "Auto (active WorkSchedule area)", "Use bbox center of active WorkSchedule"),
            ("OBJECT", "Object", "Select object/Empty as target"),
        ],
        default="AUTO",
    )
    look_at_object: PointerProperty(
        name="Target",
        type=bpy.types.Object,
        description="Target object for camera to look at",
    )

    # =====================
    # Path & Interpolation
    # =====================
    orbit_path_shape: EnumProperty(
        name="Path Shape",
        items=[
            ("CIRCLE", "Circle (Generated)", "The add-on creates a perfect circle"),
            ("CUSTOM", "Custom Path", "Use your own curve object as the path"),
        ],
        default="CIRCLE",
        description="Choose between a generated circle or a custom curve for the orbit path",
    )
    custom_orbit_path: PointerProperty(
        name="Custom Path",
        type=bpy.types.Object,
        description="Select a Curve object for the camera to follow",
        poll=lambda self, object: getattr(object, "type", None) == "CURVE",
    )
    interpolation_mode: EnumProperty(
        name="Interpolation",
        items=[
            ("LINEAR", "Linear (Constant Speed)", "Constant, mechanical speed"),
            ("BEZIER", "Bezier (Smooth)", "Smooth ease-in and ease-out for a natural feel"),
        ],
        default="LINEAR",
        description="Controls the smoothness and speed changes of the camera motion",
    )
    bezier_smoothness_factor: FloatProperty(
        name="Smoothness Factor",
        description="Controls the intensity of the ease-in/ease-out. Higher values create a more gradual transition",
        default=0.35,
        min=0.0,
        max=2.0,
        soft_min=0.0,
        soft_max=1.0,
    )

    # =====================
    # Animation settings
    # =====================
    orbit_path_method: EnumProperty(
        name="Path Method",
        items=[
            ("FOLLOW_PATH", "Follow Path (editable)", "Bezier circle + Follow Path"),
            ("KEYFRAMES", "Keyframes (lightweight)", "Animate location directly"),
        ],
        default="FOLLOW_PATH",
    )
    orbit_use_4d_duration: BoolProperty(
        name="Use 4D total frames",
        default=True,
        description="If enabled, orbit spans the whole 4D animation range",
    )
    orbit_duration_frames: FloatProperty(
        name="Orbit Duration (frames)",
        default=250.0,
        min=1.0,
        description="Custom orbit duration in frames",
    )

    # =====================
    # UI toggles
    # =====================
    show_camera_orbit_settings: BoolProperty(
        name="Camera & Orbit",
        default=False,
        description="Toggle Camera & Orbit settings visibility",
    )
    hide_orbit_path: BoolProperty(
        name="Hide Orbit Path",
        default=False,
        description="Hide the visible orbit path (Bezier Circle) in the viewport and render",
    )

    # =====================
    # 3D Texts (legacy)
    # =====================
    show_3d_schedule_texts: BoolProperty(
        name="Show 3D Schedule Texts",
        description="Toggle the visibility of the old 3D text objects",
        default=False,
        update=lambda self, context: toggle_3d_text_visibility(self, context),
    )

    # =====================
    # HUD (GPU) - Base
    # =====================
    enable_text_hud: BoolProperty(
        name="Enable Viewport HUD",
        description="Enable GPU-based HUD overlay for real-time schedule information in the viewport",
        default=False,
        update=toggle_hud_gpu,
    )
    hud_show_date: BoolProperty(name="Date", default=True, update=update_hud_gpu)
    hud_show_week: BoolProperty(name="Week", default=True, update=update_hud_gpu)
    hud_show_day: BoolProperty(name="Day", default=True, update=update_hud_gpu)
    hud_show_progress: BoolProperty(name="Progress", default=True, update=update_hud_gpu)

    hud_position: EnumProperty(
        name="Position",
        items=[
            ("TOP_RIGHT", "Top Right", ""),
            ("TOP_LEFT", "Top Left", ""),
            ("BOTTOM_RIGHT", "Bottom Right", ""),
            ("BOTTOM_LEFT", "Bottom Left", ""),
        ],
        default="TOP_RIGHT",
        update=force_hud_refresh,
    )
    hud_scale_factor: FloatProperty(
        name="Scale",
        default=1.0,
        min=0.1,
        max=5.0,
        precision=2,
        update=force_hud_refresh,
    )
    hud_margin_horizontal: FloatProperty(
        name="H-Margin",
        default=0.05,
        min=0.0,
        max=0.3,
        precision=3,
        update=force_hud_refresh,
    )
    hud_margin_vertical: FloatProperty(
        name="V-Margin",
        default=0.05,
        min=0.0,
        max=0.3,
        precision=3,
        update=force_hud_refresh,
    )

    # Base colors (RGBA)
    hud_text_color: FloatVectorProperty(
        name="Text Color",
        subtype="COLOR",
        size=4,
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        update=force_hud_refresh,
    )
    hud_background_color: FloatVectorProperty(
        name="Background Color",
        subtype="COLOR",
        size=4,
        default=(0.0, 0.0, 0.0, 0.8),
        min=0.0,
        max=1.0,
        update=force_hud_refresh,
    )

    # =====================
    # HUD VISUAL ENHANCEMENTS
    # =====================
    # Spacing & alignment
    hud_text_spacing: FloatProperty(
        name="Line Spacing",
        description="Vertical spacing between HUD text lines",
        default=0.02,
        min=0.0,
        max=0.3,
        precision=3,
        update=force_hud_refresh,
    )
    hud_text_alignment: EnumProperty(
        name="Text Alignment",
        items=[
            ("LEFT", "Left", "Align text to the left"),
            ("CENTER", "Center", "Center align text"),
            ("RIGHT", "Right", "Align text to the right"),
        ],
        default="LEFT",
        update=force_hud_refresh,
    )

    # Panel padding
    hud_padding_horizontal: FloatProperty(
        name="H-Padding",
        description="Horizontal padding inside the HUD panel",
        default=10.0,
        min=0.0,
        max=50.0,
        update=force_hud_refresh,
    )
    hud_padding_vertical: FloatProperty(
        name="V-Padding",
        description="Vertical padding inside the HUD panel",
        default=8.0,
        min=0.0,
        max=50.0,
        update=force_hud_refresh,
    )

    # Borders
    hud_border_radius: FloatProperty(
        name="Border Radius",
        description="Corner rounding of the HUD background",
        default=5.0,
        min=0.0,
        max=20.0,
        update=force_hud_refresh,
    )
    hud_border_width: FloatProperty(
        name="Border Width",
        description="Width of the HUD border",
        default=0.0,
        min=0.0,
        max=5.0,
        update=force_hud_refresh,
    )
    hud_border_color: FloatVectorProperty(
        name="Border Color",
        subtype="COLOR",
        size=4,
        default=(1.0, 1.0, 1.0, 0.5),
        min=0.0,
        max=1.0,
        update=force_hud_refresh,
    )

    # Text shadow
    hud_text_shadow_enabled: BoolProperty(
        name="Text Shadow",
        description="Enable text shadow for better readability",
        default=True,
        update=force_hud_refresh,
    )
    hud_text_shadow_offset_x: FloatProperty(
        name="Shadow Offset X",
        description="Horizontal offset of text shadow",
        default=1.0,
        min=-10.0,
        max=10.0,
        update=force_hud_refresh,
    )
    hud_text_shadow_offset_y: FloatProperty(
        name="Shadow Offset Y",
        description="Vertical offset of text shadow",
        default=-1.0,
        min=-10.0,
        max=10.0,
        update=force_hud_refresh,
    )
    hud_text_shadow_color: FloatVectorProperty(
        name="Shadow Color",
        subtype="COLOR",
        size=4,
        default=(0.0, 0.0, 0.0, 0.8),
        min=0.0,
        max=1.0,
        update=force_hud_refresh,
    )

    # Background drop shadow
    hud_background_shadow_enabled: BoolProperty(
        name="Background Shadow",
        description="Enable drop shadow for the HUD background",
        default=False,
        update=force_hud_refresh,
    )
    hud_background_shadow_offset_x: FloatProperty(
        name="BG Shadow Offset X",
        default=3.0,
        min=-20.0,
        max=20.0,
        update=force_hud_refresh,
    )
    hud_background_shadow_offset_y: FloatProperty(
        name="BG Shadow Offset Y",
        default=-3.0,
        min=-20.0,
        max=20.0,
        update=force_hud_refresh,
    )
    hud_background_shadow_blur: FloatProperty(
        name="BG Shadow Blur",
        description="Blur radius of the background shadow",
        default=5.0,
        min=0.0,
        max=20.0,
        update=force_hud_refresh,
    )
    hud_background_shadow_color: FloatVectorProperty(
        name="BG Shadow Color",
        subtype="COLOR",
        size=4,
        default=(0.0, 0.0, 0.0, 0.6),
        min=0.0,
        max=1.0,
        update=force_hud_refresh,
    )

    # Typography
    hud_font_weight: EnumProperty(
        name="Font Weight",
        items=[
            ("NORMAL", "Normal", "Normal font weight"),
            ("BOLD", "Bold", "Bold font weight"),
        ],
        default="NORMAL",
        update=force_hud_refresh,
    )
    hud_letter_spacing: FloatProperty(
        name="Letter Spacing",
        description="Spacing between characters (tracking)",
        default=0.0,
        min=-2.0,
        max=5.0,
        precision=2,
        update=force_hud_refresh,
    )

    # Background gradient
    hud_background_gradient_enabled: BoolProperty(
        name="Background Gradient",
        description="Enable gradient background instead of solid color",
        default=False,
        update=force_hud_refresh,
    )
    hud_background_gradient_color: FloatVectorProperty(
        name="Gradient Color",
        subtype="COLOR",
        size=4,
        default=(0.1, 0.1, 0.1, 0.9),
        min=0.0,
        max=1.0,
        update=force_hud_refresh,
    )
    hud_gradient_direction: EnumProperty(
        name="Gradient Direction",
        items=[
            ("VERTICAL", "Vertical", "Top to bottom gradient"),
            ("HORIZONTAL", "Horizontal", "Left to right gradient"),
            ("DIAGONAL", "Diagonal", "Diagonal gradient"),
        ],
        default="VERTICAL",
        update=force_hud_refresh,
    )


# --- COMIENZO DEL CÓDIGO CORREGIDO ---
class TaskFilterRule(PropertyGroup):
    """Define una regla de filtrado con soporte para múltiples tipos de datos."""
    is_active: BoolProperty(name="Active", default=True, description="Enable or disable this filter rule")

    column: EnumProperty(
        name="Column",
        description="The column to apply the filter on",
        items=get_all_task_columns_enum,
        update=update_filter_column
    )
    
    operator: EnumProperty(
        name="Operator",
        description="The comparison operation to perform",
        items=get_operator_items
    )
    
    # Propiedad interna para almacenar el tipo de dato actual
    data_type: StringProperty(name="Data Type", default='string')

    # Campos de valor específicos para cada tipo de dato
    value_string: StringProperty(name="Value", description="Value for text or date filters")
    value_integer: IntProperty(name="Value", description="Value for integer number filters")
    value_float: FloatProperty(name="Value", description="Value for decimal number filters")
    value_boolean: BoolProperty(name="Value", description="Value for true/false filters")
# --- FIN DEL CÓDIGO CORREGIDO ---


class BIMTaskFilterProperties(PropertyGroup):
    """Stores the complete configuration of the filter system."""
    rules: CollectionProperty(
        name="Filter Rules",
        type=TaskFilterRule,
    )
    active_rule_index: IntProperty(
        name="Active Filter Rule Index",
    )
    logic: EnumProperty(
        name="Filter Logic",
        description="How multiple filter rules are combined",
        items=[
            ('AND', "Match All (AND)", "Show tasks that meet ALL active rules"),
            ('OR', "Match Any (OR)", "Show tasks that meet AT LEAST ONE active rule"),
        ],
        default='AND',
    )
    show_filters: BoolProperty(
        name="Show Filters",
        description="Shows or hides the filter configuration panel",
        default=False,
    )
    # --- ADDED PROPERTY ---
    show_saved_filters: BoolProperty(
        name="Show Saved Filters",
        description="Shows or hides the saved filters panel",
        default=False,
    )
class SavedFilterSet(PropertyGroup):
    """Almacena un conjunto de reglas de filtro con un nombre."""
    name: StringProperty(name="Set Name")
    rules: CollectionProperty(type=TaskFilterRule)
# === FIN CÓDIGO PARA GUARDAR/CARGAR FILTROS ===

class TaskProfileGroupChoice(PropertyGroup):
    """Profile group mapping for each task"""
    group_name: StringProperty(name="Group Name")
    enabled: BoolProperty(name="Enabled")
    selected_profile: StringProperty(name="Selected Profile")
    if TYPE_CHECKING:
        group_name: str
        enabled: bool
        selected_profile: str


class Task(PropertyGroup):
    """Task properties with improved profile support"""
    # Profile mapping by group
    profile_group_choices: CollectionProperty(name="Profile Group Choices", type=TaskProfileGroupChoice)
    use_active_profile_group: BoolProperty(
        name="Use Active Group", 
        default=False, 
        update=update_use_active_profile_group
    )
    selected_profile_in_active_group: EnumProperty(
        name="Profile in Active Group",
        description="Select profile within the active custom group (excludes DEFAULT)",
        items=get_custom_group_profile_items, # â†  CAMBIO CRÃ TICO AQUÃ 
        update=update_selected_profile_in_active_group
    )
    
    # Basic task properties
    appearance_profile: EnumProperty(name="Appearance Profile", items=get_appearance_profile_items)
    name: StringProperty(name="Name", update=updateTaskName)
    identification: StringProperty(name="Identification", update=updateTaskIdentification)
    ifc_definition_id: IntProperty(name="IFC Definition ID")
    has_children: BoolProperty(name="Has Children")
    is_selected: BoolProperty(
        name="Is Selected",
        update=update_task_checkbox_selection
    )
    is_expanded: BoolProperty(name="Is Expanded")
    has_bar_visual: BoolProperty(name="Show Task Bar Animation", default=False, update=update_task_bar_list)
    level_index: IntProperty(name="Level Index")
    
    # Times
    duration: StringProperty(name="Duration", update=updateTaskDuration)
    start: StringProperty(name="Start", update=updateTaskTimeStart)
    finish: StringProperty(name="Finish", update=updateTaskTimeFinish)
    calendar: StringProperty(name="Calendar")
    derived_start: StringProperty(name="Derived Start")
    derived_finish: StringProperty(name="Derived Finish")
    derived_duration: StringProperty(name="Derived Duration")
    derived_calendar: StringProperty(name="Derived Calendar")
    
    # Relationships
    is_predecessor: BoolProperty(name="Is Predecessor")
    is_successor: BoolProperty(name="Is Successor")
    outputs_count: IntProperty(name="Outputs Count", description="Number of elements assigned as task outputs")
    
    
    if TYPE_CHECKING:
        appearance_profile: str
        name: str
        identification: str
        ifc_definition_id: int
        has_children: bool
        is_selected: bool
        is_expanded: bool
        has_bar_visual: bool
        level_index: int
        duration: str
        start: str
        finish: str
        calendar: str
        derived_start: str
        derived_finish: str
        derived_duration: str
        derived_calendar: str
        is_predecessor: bool
        is_successor: bool
        outputs_count: int


class WorkPlan(PropertyGroup):
    name: StringProperty(name="Name")
    ifc_definition_id: IntProperty(name="IFC Definition ID")
    if TYPE_CHECKING:
        name: str
        ifc_definition_id: int


class TaskResource(PropertyGroup):
    name: StringProperty(name="Name", update=updateAssignedResourceName)
    ifc_definition_id: IntProperty(name="IFC Definition ID")
    schedule_usage: FloatProperty(name="Schedule Usage", update=updateAssignedResourceUsage)
    if TYPE_CHECKING:
        name: str
        ifc_definition_id: int
        schedule_usage: float


class TaskProduct(PropertyGroup):
    name: StringProperty(name="Name")
    ifc_definition_id: IntProperty(name="IFC Definition ID")
    if TYPE_CHECKING:
        name: str
        ifc_definition_id: int


WorkPlanEditingType = Literal["-", "ATTRIBUTES", "SCHEDULES", "WORK_SCHEDULE", "TASKS", "WORKTIMES"]


class BIMWorkPlanProperties(PropertyGroup):
    work_plan_attributes: CollectionProperty(name="Work Plan Attributes", type=Attribute)
    editing_type: EnumProperty(
        items=[(i, i, "") for i in get_args(WorkPlanEditingType)],
    )
    work_plans: CollectionProperty(name="Work Plans", type=WorkPlan)
    active_work_plan_index: IntProperty(name="Active Work Plan Index")
    active_work_plan_id: IntProperty(name="Active Work Plan Id")
    work_schedules: EnumProperty(items=getWorkSchedules, name="Work Schedules")
    if TYPE_CHECKING:
        work_plan_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        editing_type: WorkPlanEditingType
        work_plans: bpy.types.bpy_prop_collection_idprop[WorkPlan]
        active_work_plan_index: int
        active_work_plan_id: int
        work_schedules: str


class IFCStatus(PropertyGroup):
    name: StringProperty(name="Name")
    is_visible: BoolProperty(
        name="Is Visible", default=True, update=lambda x, y: (None, bpy.ops.bim.activate_status_filters())[0]
    )
    if TYPE_CHECKING:
        name: str
        is_visible: bool


class BIMStatusProperties(PropertyGroup):
    is_enabled: BoolProperty(name="Is Enabled")
    statuses: CollectionProperty(name="Statuses", type=IFCStatus)
    if TYPE_CHECKING:
        is_enabled: bool
        statuses: bpy.types.bpy_prop_collection_idprop[IFCStatus]


class BIMWorkScheduleProperties(PropertyGroup):
    work_schedule_predefined_types: EnumProperty(
        items=get_schedule_predefined_types, name="Predefined Type", default=None
    )
    object_type: StringProperty(name="Object Type")
    durations_attributes: CollectionProperty(name="Durations Attributes", type=ISODuration)
    work_calendars: EnumProperty(items=getWorkCalendars, name="Work Calendars")
    work_schedule_attributes: CollectionProperty(name="Work Schedule Attributes", type=Attribute)
    editing_type: StringProperty(name="Editing Type")
    editing_task_type: StringProperty(name="Editing Task Type")
    active_work_schedule_index: IntProperty(name="Active Work Schedules Index")
    active_work_schedule_id: IntProperty(name="Active Work Schedules Id")
    active_task_index: IntProperty(name="Active Task Index", update=update_active_task_index)
    active_task_id: IntProperty(name="Active Task Id")
    highlighted_task_id: IntProperty(name="Highlited Task Id")
    task_attributes: CollectionProperty(name="Task Attributes", type=Attribute)
    should_show_visualisation_ui: BoolProperty(name="Should Show Visualisation UI", default=True, update=switch_options)
    should_show_task_bar_selection: BoolProperty(name="Add to task bar", default=False)
    should_show_snapshot_ui: BoolProperty(name="Should Show Snapshot UI", default=False, update=switch_options2)
    should_show_column_ui: BoolProperty(name="Should Show Column UI", default=False)
    columns: CollectionProperty(name="Columns", type=Attribute)
    active_column_index: IntProperty(name="Active Column Index")
    sort_column: StringProperty(name="Sort Column")
    is_sort_reversed: BoolProperty(name="Is Sort Reversed", update=update_sort_reversed)
    column_types: EnumProperty(
        items=[
            ("IfcTask", "IfcTask", ""),
            ("IfcTaskTime", "IfcTaskTime", ""),
            ("Special", "Special", ""),
        ],
        name="Column Types",
    )
    task_columns: EnumProperty(items=getTaskColumns, name="Task Columns")
    task_time_columns: EnumProperty(items=getTaskTimeColumns, name="Task Time Columns")
    other_columns: EnumProperty(
        items=[
            ("Controls.Calendar", "Calendar", ""),
        ],
        name="Special Columns",
    )
    active_task_time_id: IntProperty(name="Active Task Time Id")
    task_time_attributes: CollectionProperty(name="Task Time Attributes", type=Attribute)
    contracted_tasks: StringProperty(name="Contracted Task Items", default="[]")
    task_bars: StringProperty(name="Checked Task Items", default="[]")
    is_task_update_enabled: BoolProperty(name="Is Task Update Enabled", default=True)
    editing_sequence_type: StringProperty(name="Editing Sequence Type")
    active_sequence_id: IntProperty(name="Active Sequence Id")
    sequence_attributes: CollectionProperty(name="Sequence Attributes", type=Attribute)
    lag_time_attributes: CollectionProperty(name="Time Lag Attributes", type=Attribute)
    visualisation_start: StringProperty(name="Visualisation Start", update=update_visualisation_start)
    visualisation_finish: StringProperty(name="Visualisation Finish", update=update_visualisation_finish)
    speed_multiplier: FloatProperty(name="Speed Multiplier", default=10000)
    speed_animation_duration: StringProperty(name="Speed Animation Duration", default="1 s")
    speed_animation_frames: IntProperty(name="Speed Animation Frames", default=24)
    speed_real_duration: StringProperty(name="Speed Real Duration", default="1 w")
    speed_types: EnumProperty(
        items=[
            ("FRAME_SPEED", "Frame-based", "e.g. 25 frames = 1 real week"),
            ("DURATION_SPEED", "Duration-based", "e.g. 1 video second = 1 real week"),
            ("MULTIPLIER_SPEED", "Multiplier", "e.g. 1000 x real life speed"),
        ],
        name="Speed Type",
        default="FRAME_SPEED",
    )
    task_resources: CollectionProperty(name="Task Resources", type=TaskResource)
    active_task_resource_index: IntProperty(name="Active Task Resource Index")
    task_inputs: CollectionProperty(name="Task Inputs", type=TaskProduct)
    active_task_input_index: IntProperty(name="Active Task Input Index")
    task_outputs: CollectionProperty(name="Task Outputs", type=TaskProduct)
    active_task_output_index: IntProperty(name="Active Task Output Index")
    show_saved_profiles_section: BoolProperty(name="Show Saved Profiles", default=True)
    show_nested_outputs: BoolProperty(name="Show Nested Tasks", default=False, update=update_active_task_outputs)
    show_nested_resources: BoolProperty(name="Show Nested Tasks", default=False, update=update_active_task_resources)
    show_nested_inputs: BoolProperty(name="Show Nested Tasks", default=False, update=update_active_task_inputs)
    product_input_tasks: CollectionProperty(name="Product Task Inputs", type=TaskProduct)
    product_output_tasks: CollectionProperty(name="Product Task Outputs", type=TaskProduct)
    active_product_output_task_index: IntProperty(name="Active Product Output Task Index")
    active_product_input_task_index: IntProperty(name="Active Product Input Task Index")
    enable_reorder: BoolProperty(name="Enable Reorder", default=False)
    show_task_operators: BoolProperty(name="Show Task Options", default=True)
    should_show_schedule_baseline_ui: BoolProperty(name="Baselines", default=False)
    filter_by_active_schedule: BoolProperty(
        name="Filter By Active Schedule", default=False, update=update_filter_by_active_schedule
    )
    # Nueva propiedad para mostrar conteo de tareas seleccionadas
    selected_tasks_count: IntProperty(name="Selected Tasks Count", default=0)

    # --- INICIO DE CÓDIGO AÑADIDO ---
    # Propiedad que contendrá la configuración del filtro
    filters: PointerProperty(type=BIMTaskFilterProperties)
    # --- FIN DE CÓDIGO AÑADIDO ---
    # --- INICIO CÓDIGO AÑADIDO ---
    saved_filter_sets: CollectionProperty(type=SavedFilterSet)
    active_saved_filter_set_index: IntProperty()
    # --- FIN CÓDIGO AÑADIDO ---

    
    if TYPE_CHECKING:
        saved_filter_sets: bpy.types.bpy_prop_collection_idprop[SavedFilterSet]
        active_saved_filter_set_index: int
        work_schedule_predefined_types: str
        object_type: str
        durations_attributes: bpy.types.bpy_prop_collection_idprop[ISODuration]
        work_calendars: str
        work_schedule_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        editing_type: str
        editing_task_type: str
        active_work_schedule_index: int
        active_work_schedule_id: int
        active_task_index: int
        active_task_id: int
        highlighted_task_id: int
        task_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        should_show_visualisation_ui: bool
        should_show_task_bar_selection: bool
        should_show_snapshot_ui: bool
        should_show_column_ui: bool
        columns: bpy.types.bpy_prop_collection_idprop[Attribute]
        active_column_index: int
        sort_column: str
        is_sort_reversed: bool
        column_types: str
        task_columns: str
        task_time_columns: str
        other_columns: str
        active_task_time_id: int
        task_time_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        contracted_tasks: str
        task_bars: str
        is_task_update_enabled: bool
        editing_sequence_type: str
        active_sequence_id: int
        sequence_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        lag_time_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        visualisation_start: str
        visualisation_finish: str
        speed_multiplier: float
        speed_animation_duration: str
        speed_animation_frames: int
        speed_real_duration: str
        speed_types: str
        task_resources: bpy.types.bpy_prop_collection_idprop[TaskResource]
        active_task_resource_index: int
        task_inputs: bpy.types.bpy_prop_collection_idprop[TaskProduct]
        active_task_input_index: int
        task_outputs: bpy.types.bpy_prop_collection_idprop[TaskProduct]
        active_task_output_index: int
        show_nested_outputs: bool
        show_nested_resources: bool
        show_nested_inputs: bool
        product_input_tasks: bpy.types.bpy_prop_collection_idprop[TaskProduct]
        product_output_tasks: bpy.types.bpy_prop_collection_idprop[TaskProduct]
        active_product_output_task_index: int
        active_product_input_task_index: int
        enable_reorder: bool
        show_task_operators: bool
        should_show_schedule_baseline_ui: bool
        filter_by_active_schedule: bool
        selected_tasks_count: int
        filters: 'BIMTaskFilterProperties'


class BIMTaskTreeProperties(PropertyGroup):
    # This belongs by itself for performance reasons. https://developer.blender.org/T87737
    tasks: CollectionProperty(name="Tasks", type=Task)
    if TYPE_CHECKING:
        tasks: bpy.types.bpy_prop_collection_idprop[Task]


class WorkCalendar(PropertyGroup):
    name: StringProperty(name="Name")
    ifc_definition_id: IntProperty(name="IFC Definition ID")
    if TYPE_CHECKING:
        name: str
        ifc_definition_id: int


class RecurrenceComponent(PropertyGroup):
    name: StringProperty(name="Name")
    is_specified: BoolProperty(name="Is Specified")
    if TYPE_CHECKING:
        name: str
        is_specified: bool


class BIMWorkCalendarProperties(PropertyGroup):
    work_calendar_attributes: CollectionProperty(name="Work Calendar Attributes", type=Attribute)
    work_time_attributes: CollectionProperty(name="Work Time Attributes", type=Attribute)
    editing_type: StringProperty(name="Editing Type")
    active_work_calendar_id: IntProperty(name="Active Work Calendar Id")
    active_work_time_id: IntProperty(name="Active Work Time Id")
    day_components: CollectionProperty(name="Day Components", type=RecurrenceComponent)
    weekday_components: CollectionProperty(name="Weekday Components", type=RecurrenceComponent)
    month_components: CollectionProperty(name="Month Components", type=RecurrenceComponent)
    position: IntProperty(name="Position")
    interval: IntProperty(name="Recurrence Interval")
    occurrences: IntProperty(name="Occurs N Times")
    recurrence_types: EnumProperty(
        items=[
            ("DAILY", "Daily", "e.g. Every day"),
            ("WEEKLY", "Weekly", "e.g. Every Friday"),
            ("MONTHLY_BY_DAY_OF_MONTH", "Monthly on Specified Date", "e.g. Every 2nd of each Month"),
            ("MONTHLY_BY_POSITION", "Monthly on Specified Weekday", "e.g. Every 1st Friday of each Month"),
            ("YEARLY_BY_DAY_OF_MONTH", "Yearly on Specified Date", "e.g. Every 2nd of October"),
            ("YEARLY_BY_POSITION", "Yearly on Specified Weekday", "e.g. Every 1st Friday of October"),
        ],
        name="Recurrence Types",
    )
    start_time: StringProperty(name="Start Time")
    end_time: StringProperty(name="End Time")
    if TYPE_CHECKING:
        work_calendar_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        work_time_attributes: bpy.types.bpy_prop_collection_idprop[Attribute]
        editing_type: str
        active_work_calendar_id: int
        active_work_time_id: int
        day_components: bpy.types.bpy_prop_collection_idprop[RecurrenceComponent]
        weekday_components: bpy.types.bpy_prop_collection_idprop[RecurrenceComponent]
        month_components: bpy.types.bpy_prop_collection_idprop[RecurrenceComponent]
        position: int
        interval: int
        occurrences: int
        recurrence_types: str
        start_time: str
        end_time: str


def update_selected_date(self: "DatePickerProperties", context: bpy.types.Context) -> None:
    include_time = True
    selected_date = tool.Sequence.parse_isodate_datetime(self.selected_date, include_time)
    selected_date = selected_date.replace(hour=self.selected_hour, minute=self.selected_min, second=self.selected_sec)
    self.selected_date = tool.Sequence.isodate_datetime(selected_date, include_time)


class DatePickerProperties(PropertyGroup):
    display_date: StringProperty(
        name="Display Date",
        description="Needed to keep track of what month is currently opened in date picker without affecting the currently selected date.",
    )
    selected_date: StringProperty(name="Selected Date")
    selected_hour: IntProperty(min=0, max=23, update=update_selected_date)
    selected_min: IntProperty(min=0, max=59, update=update_selected_date)
    selected_sec: IntProperty(min=0, max=59, update=update_selected_date)
    if TYPE_CHECKING:
        display_date: str
        selected_date: str
        selected_hour: int
        selected_min: int
        selected_sec: int


class BIMDateTextProperties(PropertyGroup):
    start_frame: IntProperty(name="Start Frame")
    total_frames: IntProperty(name="Total Frames")
    start: StringProperty(name="Start")
    finish: StringProperty(name="Finish")
    if TYPE_CHECKING:
        start_frame: int
        total_frames: int
        start: str
        finish: str


class BIMTaskTypeColor(PropertyGroup):
    """Color by task type (legacy - maintain for compatibility)"""
    name: StringProperty(name="Name")
    animation_type: StringProperty(name="Type")
    color: FloatVectorProperty(
        name="Color",
        subtype="COLOR", size=4,
        default=(1.0, 0.0, 0.0, 1.0),
        min=0.0,
        max=1.0,
    )
    if TYPE_CHECKING:
        name: str
        animation_type: str
        color: tuple[float, float, float, float]


def update_profile_considerations(self, context):
    """
    Asegura que no se pueda tener "Start" y "End" activos si "Active" está inactivo.
    Esta es una combinación sin sentido lógico en la animación.
    """
    try:
        if getattr(self, "consider_start", False) and getattr(self, "consider_end", False) and not getattr(self, "consider_active", True):
            # Forzar que Active sea True si Start y End están activos
            self.consider_active = True
        elif (not getattr(self, "consider_active", True)) and getattr(self, "consider_start", False) and getattr(self, "consider_end", False):
            # Opcional: si se intenta desactivar Active con Start y End activos, desactivar End
            self.consider_end = False
    except Exception:
        # No romper la UI si el PG aún no está totalmente inicializado
        pass


class AppearanceProfile(PropertyGroup):
    """Appearance profile for 4D animation"""
    name: StringProperty(name="Profile Name", default="New Profile")
    
    # Considered States
    consider_start: BoolProperty(
        name="Start state", 
        default=False,
        description="When enabled, elements use start appearance throughout the entire animation, "
                   "useful for existing elements, demolition context, or persistent visibility",
        update=update_profile_considerations)
    consider_active: BoolProperty(
        name="Active state", 
        default=True,
        description="Apply appearance during task execution period",
        update=update_profile_considerations)
    consider_end: BoolProperty(
        name="End state", 
        default=True,
        description="Apply appearance after task completion",
        update=update_profile_considerations)
    
    # Colors by State
    start_color: FloatVectorProperty(
        name="Start Color",
        subtype="COLOR",
        size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )
    in_progress_color: FloatVectorProperty(
        name="In Progress Color",
        subtype="COLOR",
        size=4, min=0.0, max=1.0,
        default=(0.8, 0.8, 0.0, 1.0),
    )
    end_color: FloatVectorProperty(
        name="End Color",
        subtype="COLOR",
        size=4, min=0.0, max=1.0,
        default=(0.0, 1.0, 0.0, 1.0),
    )
    
    # Option to keep original color
    use_start_original_color: BoolProperty(name="Start: Use Original Color", default=False)
    use_active_original_color: BoolProperty(name="Active: Use Original Color", default=False)
    use_end_original_color: BoolProperty(name="End: Use Original Color", default=True)
    
    # Transparency Control
    start_transparency: FloatProperty(name="Start Transparency", min=0.0, max=1.0, default=0.0)
    active_start_transparency: FloatProperty(name="Active Start Transparency", min=0.0, max=1.0, default=0.0)
    active_finish_transparency: FloatProperty(name="Active Finish Transparency", min=0.0, max=1.0, default=0.0)
    active_transparency_interpol: FloatProperty(name="Transparency Interpol.", min=0.0, max=1.0, default=1.0)
    end_transparency: FloatProperty(name="End Transparency", min=0.0, max=1.0, default=0.0)

    hide_at_end: BoolProperty(name="Hide When Finished", description="If enabled, the object will become invisible in the End phase", default=False)
    
    if TYPE_CHECKING:
        name: str
        start_color: tuple[float, float, float, float]
        in_progress_color: tuple[float, float, float, float]
        end_color: tuple[float, float, float, float]
        use_start_original_color: bool
        use_active_original_color: bool
        use_end_original_color: bool
        start_transparency: float
        active_start_transparency: float
        active_finish_transparency: float
        active_transparency_interpol: float
        end_transparency: float
        hide_at_end: bool


class AnimationProfileGroupItem(PropertyGroup):
    """Item for animation group stack"""
    group: EnumProperty(name="Group", items=get_internal_profile_sets_enum)
    enabled: BoolProperty(name="Use", default=True)


class BIMAnimationProperties(PropertyGroup):
    """Animation properties with improved profile system"""
    
    # Unified profile system
    active_profile_system: EnumProperty(
        name="Profile System",
        items=[
            ("PROFILES", "Appearance Profiles", "Use advanced profile system"),
        ],
        default="PROFILES"
    )
    
    # Animation group stack
    animation_group_stack: CollectionProperty(name="Animation Group Stack", type=AnimationProfileGroupItem)
    animation_group_stack_index: IntProperty(name="Animation Group Stack Index", default=-1)
    
    # State and configuration
    is_editing: BoolProperty(name="Is Loaded", default=False)
    saved_profile_name: StringProperty(name="Profile Set Name", default="Default")
    
    # Appearance profiles
    profiles: CollectionProperty(name="Appearance Profiles", type=AppearanceProfile)
    active_profile_index: IntProperty(name="Active Profile Index")
    profile_groups: EnumProperty(name="Profile Group", items=get_internal_profile_sets_enum, update=update_profile_group)

    # --- INICIO DE LA MODIFICACIÃ“N ---
    # Propiedad nueva, solo para la UI del panel de Tareas, que excluye 'DEFAULT'
    task_profile_group_selector: EnumProperty(
        name="Custom Profile Group",
        items=get_user_created_groups_enum,
        update=update_task_profile_group_selector
    )
    # --- FIN DE LA MODIFICACIÃ“N ---
    
    # UI toggles
    show_saved_task_profiles_panel: BoolProperty(name="Show Saved Profiles", default=False)
    should_show_task_bar_options: BoolProperty(name="Show Task Bar Options", default=False)
    
    # Task bar colors
    color_full: FloatVectorProperty(
        name="Full Bar",
        subtype="COLOR", size=4,
        default=(1.0, 0.0, 0.0, 1.0),
        min=0.0, max=1.0,
        description="Color for full task bar",
        update=update_color_full,
    )
    color_progress: FloatVectorProperty(
        name="Progress Bar",
        subtype="COLOR", size=4,
        default=(0.0, 1.0, 0.0, 1.0),
        min=0.0, max=1.0,
        description="Color for progress task bar",
        update=update_color_progress,
    )
    
    # Legacy properties (maintain for compatibility)
    saved_color_schemes: EnumProperty(items=get_saved_color_schemes, name="Saved Colour Schemes")
    active_color_component_outputs_index: IntProperty(name="Active Color Component Index")
    active_color_component_inputs_index: IntProperty(name="Active Color Component Index")
    if TYPE_CHECKING:
        active_profile_system: str
        animation_group_stack: bpy.types.bpy_prop_collection_idprop[AnimationProfileGroupItem]
        animation_group_stack_index: int
        is_editing: bool
        saved_profile_name: str
        profiles: bpy.types.bpy_prop_collection_idprop[AppearanceProfile]
        active_profile_index: int
        profile_groups: str
        task_profile_group_selector: str
        show_saved_task_profiles_panel: bool
        should_show_task_bar_options: bool
        color_full: Color
        color_progress: Color
        saved_color_schemes: str
        active_color_component_outputs_index: int
        active_color_component_inputs_index: int


# === Camera & Orbit Settings (safe-inject) ===================================
# We attach properties dynamically to BIMAnimationProperties so we don't depend
# on the exact class body location. This works as long as registration happens
# after these attributes exist.

try:
    from bpy.props import FloatProperty, BoolProperty, EnumProperty, PointerProperty
    import bpy
    from bpy.types import Object as _BpyObject

    _C = BIMAnimationProperties  # type: ignore[name-defined]

    def _add_prop(cls, name, pdef):
        # Ensure annotation slot exists for Blender 2.8+ registration
        try:
            ann = getattr(cls, "__annotations__", None)
            if ann is None:
                cls.__annotations__ = {}
            if name not in cls.__annotations__:
                cls.__annotations__[name] = pdef
        except Exception:
            pass
        # Attach descriptor if missing
        if not hasattr(cls, name):
            setattr(cls, name, pdef)

    # --- Camera ---
    _add_prop(_C, "camera_focal_mm", FloatProperty(name="Focal (mm)", default=35.0, min=1.0, max=300.0))
    _add_prop(_C, "camera_clip_start", FloatProperty(name="Clip Start", default=0.1, min=0.0001))
    _add_prop(_C, "camera_clip_end", FloatProperty(name="Clip End", default=10000.0, min=1.0))

    # --- Orbit ---
    _add_prop(_C, "orbit_mode", EnumProperty(
        name="Orbit Mode",
        items=[
            ("NONE", "None (Static)", "No orbit animation"),
            ("CIRCLE_360", "Circle 360°", "Full circular orbit"),
            ("PINGPONG", "Ping-Pong", "Back and forth over an arc"),
        ],
        default="CIRCLE_360"
    ))

    _add_prop(_C, "orbit_radius_mode", EnumProperty(
        name="Radius Mode",
        items=[("AUTO", "Auto (from bbox)", "Compute radius from WorkSchedule bbox"),
               ("MANUAL", "Manual", "Use manual radius value")],
        default="AUTO"
    ))
    _add_prop(_C, "orbit_radius", FloatProperty(name="Radius (m)", default=10.0, min=0.01))
    _add_prop(_C, "orbit_height", FloatProperty(name="Height (Z offset)", default=8.0))
    _add_prop(_C, "orbit_start_angle_deg", FloatProperty(name="Start Angle (deg)", default=0.0))
    _add_prop(_C, "orbit_direction", EnumProperty(
        name="Direction",
        items=[("CCW", "CCW", "Counter-clockwise"), ("CW", "CW", "Clockwise")],
        default="CCW"
    ))

    # --- Look At ---
    _add_prop(_C, "look_at_mode", EnumProperty(
        name="Look At",
        items=[("AUTO", "Auto (active WorkSchedule area)", "Use bbox center of active WorkSchedule"),
               ("OBJECT", "Object", "Select object/Empty as target")],
        default="AUTO"
    ))
    _add_prop(_C, "look_at_object", PointerProperty(name="Target", type=_BpyObject))

    # --- NEW: Path Shape & Custom Path ---
    _add_prop(_C, "orbit_path_shape", EnumProperty(
        name="Path Shape",
        items=[
            ('CIRCLE', "Circle (Generated)", "The add-on creates a perfect circle"),
            ('CUSTOM', "Custom Path", "Use your own curve object as the path"),
        ],
        default='CIRCLE',
    ))
    _add_prop(_C, "custom_orbit_path", PointerProperty(
        name="Custom Path",
        type=_BpyObject,
        poll=lambda self, object: getattr(object, "type", None) == 'CURVE'
    ))

    # --- NEW: Interpolation ---
    _add_prop(_C, "interpolation_mode", EnumProperty(
        name="Interpolation",
        items=[
            ('LINEAR', "Linear (Constant Speed)", "Constant, mechanical speed"),
            ('BEZIER', "Bezier (Smooth)", "Smooth ease-in and ease-out for a natural feel"),
        ],
        default='LINEAR',
    ))


    _add_prop(_C, "bezier_smoothness_factor", FloatProperty(
        name="Smoothness Factor",
        description="Controls the intensity of the ease-in/ease-out. Higher values create a more gradual transition",
        default=0.35,
        min=0.0,
        max=2.0,
        soft_min=0.0,
        soft_max=1.0
    ))
    # --- Animation method & duration ---
    _add_prop(_C, "orbit_path_method", EnumProperty(
        name="Path Method",
        items=[("FOLLOW_PATH", "Follow Path (editable)", "Bezier circle + Follow Path"),
               ("KEYFRAMES", "Keyframes (lightweight)", "Animate location directly")],
        default="FOLLOW_PATH"
    ))
    _add_prop(_C, "orbit_use_4d_duration", BoolProperty(
        name="Use 4D total frames", default=True,
        description="If enabled, orbit spans the whole 4D animation range"))
    _add_prop(_C, "orbit_duration_frames", FloatProperty(
        name="Orbit Duration (frames)", default=250.0, min=1.0))

    # --- UI toggles ---
    _add_prop(_C, "show_camera_orbit_settings", BoolProperty(
        name="Camera & Orbit", default=False, description="Toggle Camera & Orbit settings visibility"))
    

    _add_prop(_C, "hide_orbit_path", BoolProperty(
        name="Hide Orbit Path", default=False,
        description="Hide the visible orbit path (Bezier Circle) in the viewport and render"))

    # --- HUD (Heads-Up Display) properties mirrored on BIMAnimationProperties ---
    _add_prop(_C, "enable_text_hud", BoolProperty(
        name="Enable Text HUD",
        description="Attach schedule texts as HUD elements to the active camera",
        default=False, update=toggle_hud_gpu))
    _add_prop(_C, "hud_margin_horizontal", FloatProperty(
        name="Horizontal Margin",
        description="Distance from camera edge (percentage of camera width)",
        default=0.05, min=0.0, max=0.3, precision=3,
        update=update_hud_gpu))
    _add_prop(_C, "hud_margin_vertical", FloatProperty(
        name="Vertical Margin",
        description="Distance from camera edge (percentage of camera height)",
        default=0.05, min=0.0, max=0.3, precision=3,
        update=update_hud_gpu))
    _add_prop(_C, "hud_text_spacing", FloatProperty(
        name="Text Spacing",
        description="Vertical spacing between HUD text elements",
        default=0.02, min=0.0, max=0.2, precision=3,
        update=update_hud_gpu))
    _add_prop(_C, "hud_scale_factor", FloatProperty(
        name="HUD Scale Factor",
        description="Scale multiplier for HUD elements relative to camera distance",
        default=1.0, min=0.1, max=5.0, precision=2,
        update=update_hud_gpu))
    _add_prop(_C, "hud_distance", FloatProperty(
        name="Distance",
        description="Distance from camera to place HUD elements",
        default=3.0, min=0.5, max=50.0, precision=1,
        update=update_hud_gpu))

    _add_prop(_C, "hud_position", EnumProperty(
        name="HUD Position",
        description="Position of HUD elements on screen",
        items=[
            ('TOP_LEFT', "Top Left", "Position HUD at top-left corner"),
            ('TOP_RIGHT', "Top Right", "Position HUD at top-right corner"),
            ('BOTTOM_LEFT', "Bottom Left", "Position HUD at bottom-left corner"),
            ('BOTTOM_RIGHT', "Bottom Right", "Position HUD at bottom-right corner"),
        ],
        default='TOP_RIGHT',
        update=update_hud_gpu))



except Exception as _e:
    # Failsafe: leave file importable if Bonsai internals are not present here
    pass
# === End Camera & Orbit Settings ====================================================================================
