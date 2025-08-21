# Bonsai - OpenBIM Blender Add-on
# HUD Compositor System for High-Quality Renders
# Copyright (C) 2024

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

# Instancia global
hud_compositor_instance = None

class HUDCompositor:
    """Sistema de compositor para HUD en renders de alta calidad"""
    def __init__(self):
        self.hud_group_name = "HUD_Schedule_Group"
        self.text_objects = []
        self.background_object = None

    def setup_compositor_hud(self, scene):
        try:
            scene.use_nodes = True
            tree = scene.node_tree
            self.cleanup_hud_nodes(tree)
            hud_nodes = self.create_hud_node_structure(tree, scene)
            self.connect_hud_to_pipeline(tree, hud_nodes)
            print("✅ Compositor HUD configurado correctamente")
            return True
        except Exception as e:
            print(f"❌ Error configurando compositor HUD: {e}")
            return False

    def cleanup_hud_nodes(self, tree):
        nodes_to_remove = [n for n in tree.nodes if n.name.startswith("HUD_")]
        for node in nodes_to_remove:
            tree.nodes.remove(node)

    def create_hud_node_structure(self, tree, scene):
        render_layers = self.get_or_create_render_layers(tree)
        self.create_hud_3d_objects(scene)
        
        hud_render_layer = tree.nodes.new(type='CompositorNodeRLayers')
        hud_render_layer.name = "HUD_Render_Layer"
        hud_render_layer.location = (0, -300)
        hud_render_layer.layer = "HUD_Layer"
        
        alpha_over = tree.nodes.new(type='CompositorNodeAlphaOver')
        alpha_over.name = "HUD_Alpha_Over"
        alpha_over.location = (400, 200)
        alpha_over.use_premultiply = True
        
        return {'render_layers': render_layers, 'hud_render': hud_render_layer, 'alpha_over': alpha_over}

    def connect_hud_to_pipeline(self, tree, hud_nodes):
        composite = next((n for n in tree.nodes if n.type == 'COMPOSITE'), None)
        if not composite:
            composite = tree.nodes.new(type='CompositorNodeComposite')
            composite.location = (600, 200)
            
        # Conectar salida original al composite
        original_output = hud_nodes['render_layers'].outputs['Image']
        
        # Conectar render principal y HUD al Alpha Over
        tree.links.new(original_output, hud_nodes['alpha_over'].inputs[1])
        tree.links.new(hud_nodes['hud_render'].outputs['Image'], hud_nodes['alpha_over'].inputs[2])
        
        # Conectar el resultado al Composite final
        tree.links.new(hud_nodes['alpha_over'].outputs['Image'], composite.inputs['Image'])

    def get_or_create_render_layers(self, tree):
        main_rl = next((n for n in tree.nodes if n.type == 'R_LAYERS' and not n.name.startswith("HUD_")), None)
        if main_rl:
            return main_rl
        render_layers = tree.nodes.new(type='CompositorNodeRLayers')
        render_layers.location = (0, 200)
        return render_layers

    def create_hud_3d_objects(self, scene):
        hud_collection = self.get_or_create_hud_collection(scene)
        self.cleanup_hud_objects(hud_collection)
        
        hud_elements = [
            {"name": "HUD_Date", "type": "date", "offset": (0, 0, 0)},
            {"name": "HUD_Week", "type": "week", "offset": (0, -0.4, 0)},
            {"name": "HUD_Day", "type": "day", "offset": (0, -0.8, 0)},
            {"name": "HUD_Progress", "type": "progress", "offset": (0, -1.2, 0)}
        ]
        
        self.text_objects = []
        for element in hud_elements:
            text_obj = self.create_hud_text_object(scene, element["name"], element["type"], element["offset"])
            if text_obj:
                hud_collection.objects.link(text_obj)
                self.text_objects.append(text_obj)
                
        self.background_object = self.create_hud_background(scene, hud_collection)
        self.setup_hud_render_layer(scene, hud_collection)

    def get_or_create_hud_collection(self, scene):
        collection_name = "HUD_Schedule_Objects"
        if collection_name in bpy.data.collections:
            return bpy.data.collections[collection_name]
        collection = bpy.data.collections.new(collection_name)
        scene.collection.children.link(collection)
        return collection

    def cleanup_hud_objects(self, collection):
        for obj in list(collection.objects):
            if "is_hud_element" in obj or "is_hud_background" in obj:
                bpy.data.objects.remove(obj, do_unlink=True)

    def create_hud_text_object(self, scene, name, hud_type, offset):
        try:
            font_curve = bpy.data.curves.new(name=f"{name}_curve", type='FONT')
            font_curve.body = "..."
            font_curve.size = 0.08
            font_curve.align_x, font_curve.align_y = 'LEFT', 'TOP'
            
            text_obj = bpy.data.objects.new(name, font_curve)
            text_obj.parent = scene.camera
            text_obj.location = Vector((0.6, 0.45, -2.0)) + Vector(offset)
            text_obj.rotation_euler = (0, 0, 0)
            
            self.setup_hud_material(text_obj)
            text_obj["is_hud_element"], text_obj["hud_type"] = True, hud_type
            return text_obj
        except Exception as e:
            print(f"Error creando texto HUD: {e}")
            return None

    def create_hud_background(self, scene, collection):
        try:
            mesh = bpy.data.meshes.new("HUD_Background_mesh")
            bm = bmesh.new()
            bm.verts.new((0.55, 0.55, -2.0))
            bm.verts.new((2.2, 0.55, -2.0))
            bm.verts.new((2.2, -0.2, -2.0))
            bm.verts.new((0.55, -0.2, -2.0))
            bm.verts.ensure_lookup_table()
            bm.faces.new(bm.verts)
            bm.to_mesh(mesh)
            bm.free()
            
            bg_obj = bpy.data.objects.new("HUD_Background", mesh)
            bg_obj.parent = scene.camera
            self.setup_background_material(bg_obj)
            collection.objects.link(bg_obj)
            bg_obj["is_hud_background"] = True
            return bg_obj
        except Exception as e:
            print(f"Error creando fondo HUD: {e}")
            return None

    def setup_hud_material(self, obj):
        mat = bpy.data.materials.new(f"HUD_Text_Material")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs['Emission'].default_value = (1, 1, 1, 1)
        bsdf.inputs['Emission Strength'].default_value = 5.0
        obj.data.materials.append(mat)

    def setup_background_material(self, obj):
        mat = bpy.data.materials.new("HUD_Background_Material")
        mat.use_nodes, mat.blend_method = True, 'BLEND'
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1)
        bsdf.inputs['Alpha'].default_value = 0.6
        obj.data.materials.append(mat)

    def setup_hud_render_layer(self, scene, hud_collection):
        hud_layer_name = "HUD_Layer"
        if hud_layer_name not in scene.view_layers:
            hud_layer = scene.view_layers.new(hud_layer_name)
        else:
            hud_layer = scene.view_layers[hud_layer_name]
        
        root_lc = hud_layer.layer_collection
        for lc in root_lc.children:
            lc.exclude = lc.collection != hud_collection

    def update_hud_content(self, scene):
        hud_data = self.get_schedule_data_for_frame(scene)
        if not hud_data: return
        for text_obj in self.text_objects:
            if text_obj and text_obj.data and "hud_type" in text_obj:
                text_obj.data.body = self.format_hud_text(text_obj["hud_type"], hud_data)

    def get_schedule_data_for_frame(self, scene):
        try:
            import bonsai.tool as tool
            viz_start, viz_finish = tool.Sequence.get_visualization_date_range()
            if not (viz_start and viz_finish): return None
            
            progress = (scene.frame_current - scene.frame_start) / (scene.frame_end - scene.frame_start)
            current_date = viz_start + ((viz_finish - viz_start) * max(0.0, min(1.0, progress)))
            
            total_days = (viz_finish - viz_start).days + 1
            elapsed_days = (current_date - viz_start).days + 1
            
            return {
                'current_date': current_date, 'week_number': ((elapsed_days - 1) // 7) + 1,
                'elapsed_days': elapsed_days, 'total_days': total_days,
                'progress_pct': round((elapsed_days / total_days) * 100), 'day_of_week': current_date.strftime('%A')
            }
        except Exception:
            return None

    def format_hud_text(self, hud_type, data):
        if hud_type == "date": return data['current_date'].strftime('%d %B %Y')
        if hud_type == "week": return f"Week {data['week_number']} - {data['day_of_week']}"
        if hud_type == "day": return f"Day {data['elapsed_days']} of {data['total_days']}"
        if hud_type == "progress": return f"Progress: {data['progress_pct']}%"
        return "HUD"

@persistent
def update_hud_compositor_handler(scene):
    global hud_compositor_instance
    if hud_compositor_instance:
        hud_compositor_instance.update_hud_content(scene)

def register_compositor_handler():
    global hud_compositor_instance
    if not hud_compositor_instance:
        hud_compositor_instance = HUDCompositor()
    if update_hud_compositor_handler not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(update_hud_compositor_handler)

def unregister_compositor_handler():
    global hud_compositor_instance
    if update_hud_compositor_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(update_hud_compositor_handler)
    hud_compositor_instance = None