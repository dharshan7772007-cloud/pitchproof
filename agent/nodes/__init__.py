"""
agent/nodes/
-------------
Individual LangGraph node implementations.

Each module exposes a single callable with signature:
    def <node_name>(state: PitchproofState) -> dict:
        ...
        return {"<owned_field>": <value>, "current_stage": "<next_stage>"}
"""
