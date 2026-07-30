from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from rhino_mcp.rhino_tools import RhinoTools, RhinoConnection
from typing import Dict, Any
import logging
import json
import argparse

# configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebServer")

# create FastAPI app
app = FastAPI()

# allow cross-domain requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# create MCP instance and tools
mcp = FastMCP("RhinoMCP")
rhino_tools = RhinoTools(mcp)

# add strategy
@mcp.prompt()
def rhino_creation_strategy() -> str:
    """Defines the preferred strategy for creating and managing objects in Rhino"""
    return """When working with Rhino through MCP, follow these guidelines:

    Especially when working with geometry, iterate with smaller steps and check the scene state from time to time.
    Act strategically with a long-term plan, think about how to organize the data and scene objects in a way that is easy to maintain and extend, by using layers and metadata (name, description),
    with the get_rhino_objects_with_metadata() function you can filter and select objects based on this metadata. You can access objects, and with the "type" attribute you can check their geometry type and
    access the geometry specific properties (such as corner points etc.) to create more complex scenes with spatial consistency. Start from sparse to detail (e.g. first the building plot, then the wall, then the window etc. - it is crucial to use metadata to be able to do that)

    1. Scene Context Awareness:
       - Always start by calling get_rhino_scene_info() with NO arguments for orientation - it returns
         `totals` plus a depth-2 layer-tree rollup, not every layer. On large models this can be
         hundreds of thousands of objects across thousands of layers, so don't dump everything at once.
       - A node's object_count is a cumulative subtree total that overlaps between ancestors and
         descendants - never sum it across nodes; totals.objects is authoritative. direct_object_count
         is the non-overlapping per-layer figure. descendant_layers == 0 means a genuine leaf.
       - Then pass layer_prefix to drill into a branch, and use get_rhino_objects_with_metadata() for
         object-level detail.
       - Hidden objects are included by default, flagged via per-layer is_visible/is_locked - don't
         assume an invisible layer is empty.
       - Use the capture_rhino_viewport to get an image from viewport to get a quick overview of the scene
       - The short_id in metadata can be displayed in viewport using capture_rhino_viewport()

    2. Object Creation and Management:
       - When creating objects, ALWAYS call add_rhino_object_metadata() after creation (The add_rhino_object_metadata() function is provided in the code context)   
       - Use meaningful names for objects to help with you with later identification, organize the scenes with layers (but not too many layers)
       - Think about grouping objects (e.g. two planes that form a window)

    3. Code Execution:
       - This runs on Rhino 8's IronPython 2.7 (not CPython 3) - write Python 2.7-compatible code: no
         f-strings, no walrus operator, no type hints, no keyword-only args. Use "{0}".format(...) instead.
       - Integer division floors under Python 2: `800/1920` == 0, not 0.41666 - use `float(...)` explicitly
         when you want a fractional result.
       - `import idpartners` does NOT work - it fails under IronPython 2 with a PEP 263 non-ASCII/encoding error.
       - print() output is NOT captured - Python 2's print is a statement, so the injected capture function
         is bypassed and printed_output comes back empty. Write values to a file and read them back, or
         return them via a result variable.
       - Non-ASCII is dangerous - decoding names with e.g. German umlauts has raised `'unknown' codec can't
         decode byte 0xf6`. Built-in scene queries are guarded by _safe_str(), but be careful with your own
         string handling.
       - Prefer automated solutions over user interaction, unless its requested or it makes sense or you struggle with errors
       - You can use rhino command syntax to ask the user questions e.g. "should i do "A" or "B"" where A,B are clickable options
       - If you got an error related to the RhinoScriptSyntax, always use the look_up_RhinoScriptSyntax tool to look up the correct syntax

    4. Best Practices:
       - Keep objects organized in appropriate layers
       - Use meaningful names and descriptions
       - Use viewport captures to verify visual results
    """


# HTTP endpoint
@app.post("/rhino/command")
async def execute_command(command: Dict[str, Any]):
    """execute Rhino command"""
    try:
        result = rhino_tools.execute_command(command)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Command execution error: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/rhino/scene")
async def get_scene():
    """get scene info"""
    try:
        scene_info = rhino_tools.get_rhino_scene_info()
        return {"status": "success", "data": scene_info}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/rhino/strategy")
async def get_strategy():
    """get Rhino strategy"""
    return {
        "rhino_strategy": rhino_creation_strategy(),
    }

# WebSocket endpoint
@app.websocket("/rhino/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    rhino_conn = RhinoConnection(port=9876)
    
    try:
        # connect to Rhino
        rhino_conn.connect()
        logger.info("Connected to Rhino socket server")
        
        # send initial connection success message
        await websocket.send_json({
            "status": "connected",
            "message": "Connected to Rhino socket server"
        })
        
        # main message loop
        while True:
            try:
                # wait for message
                data = await websocket.receive_json()
                logger.info(f"Received command: {data}")
                
                # send command to Rhino
                result = rhino_conn.send_command(data["type"], data.get("params", {}))
                
                # send result
                await websocket.send_json({
                    "status": "success",
                    "data": result
                })
                
            except json.JSONDecodeError:
                await websocket.send_json({
                    "status": "error",
                    "message": "Invalid JSON format"
                })
            except Exception as e:
                logger.error(f"Command execution error: {str(e)}")
                await websocket.send_json({
                    "status": "error",
                    "message": str(e)
                })
                
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        try:
            await websocket.send_json({
                "status": "error",
                "message": f"Connection error: {str(e)}"
            })
        except:
            pass
            
    finally:
        # clean up connection
        try:
            rhino_conn.disconnect()
            logger.info("Disconnected from Rhino socket server")
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000, help="Web server port")
    parser.add_argument("--host", type=str, default="localhost", help="Web server host")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port) 