bl_info = {
    "name": "Blender Texture Generator",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > TextureGen Tab",
    "description": "Generate and apply textures to selected meshes using an external script.",
    "category": "Object",
}

import bpy
import os
import requests
import json

class GenerateTextureOperator(bpy.types.Operator):
    """Operator to generate and apply texture to the selected mesh"""
    bl_idname = "object.generate_texture"
    bl_label = "Generate Texture"

    # Define the property correctly
    texture_type = bpy.props.StringProperty(name="Texture Type", default="metal")

    def execute(self, context):
        # Ensure a mesh is selected
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object.")
            return {'CANCELLED'}

        # Update the path to texture_generator.py (renamed from code.py)
        script_path = os.path.join(r"c:\Users\THIVAKAR\OneDrive\Desktop\G\static", "texture_generator.py")
        if not os.path.exists(script_path):
            self.report({'ERROR'}, "texture_generator.py not found in the specified directory.")
            return {'CANCELLED'}

        # Generate the texture using the external script
        try:
            # Correctly pass the value of the texture_type property
            texture_type_value = context.scene.texture_type  # Get the actual value of the property
            prompt = f"Seamless {texture_type_value} surface texture, realistic PBR material, suitable for Blender."
            output_filename = f"blender_{texture_type_value}_texture.png"

            # Use the explicit IP address
            response = requests.post(
                "http://127.0.0.1:5000/generate_texture",
                json={"prompt": prompt, "output_filename": output_filename}
            )
            response.raise_for_status()
            texture_path = response.json().get("file_path")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate texture: {e}")
            return {'CANCELLED'}

        # Apply the texture to the selected mesh
        if texture_path and os.path.exists(texture_path):
            # Unwrap the mesh
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.uv.smart_project()
            bpy.ops.object.mode_set(mode='OBJECT')

            # Create a new material
            mat = bpy.data.materials.new(name=f"{self.texture_type}_Material")
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")

            # Add an image texture node
            tex_image = mat.node_tree.nodes.new('ShaderNodeTexImage')
            tex_image.image = bpy.data.images.load(texture_path)
            mat.node_tree.links.new(bsdf.inputs['Base Color'], tex_image.outputs['Color'])

            # Assign the material to the object
            if len(obj.data.materials):
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

            self.report({'INFO'}, f"Texture applied successfully: {texture_path}")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Generated texture file not found.")
            return {'CANCELLED'}

class GenerateTexturePanel(bpy.types.Panel):
    """Panel for the texture generation addon"""
    bl_label = "Texture Generator"
    bl_idname = "OBJECT_PT_generate_texture"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'TextureGen'

    def draw(self, context):
        layout = self.layout
        layout.label(text="Generate Texture for Selected Mesh")
        layout.prop(context.scene, "texture_type")
        layout.operator(GenerateTextureOperator.bl_idname)

# Register and unregister classes
def register():
    bpy.utils.register_class(GenerateTextureOperator)
    bpy.utils.register_class(GenerateTexturePanel)
    bpy.types.Scene.texture_type = bpy.props.StringProperty(name="Texture Type", default="metal")

def unregister():
    bpy.utils.unregister_class(GenerateTextureOperator)
    bpy.utils.unregister_class(GenerateTexturePanel)
    del bpy.types.Scene.texture_type

if __name__ == "__main__":
    register()
