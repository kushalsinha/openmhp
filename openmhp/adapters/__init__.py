"""Adapters: put hardware already controlled by another layer behind MHP.

    from openmhp.adapters import BoundDriver, Signal, Setting, Action   # any Python callable
    from openmhp.adapters.sila2 import sila_device                      # SiLA 2 servers
    from openmhp.adapters.pylabrobot import plr_device                  # PyLabRobot machines
    from openmhp.adapters.madsci import madsci_node                     # MADSci nodes
    from openmhp.adapters.opcua import opcua_device                     # OPC UA servers / PLCs
    from openmhp.adapters.ros2 import ros2_device                       # ROS 2 nodes

Each returns a Driver; serve it with `mhp serve`, register it in a Directory,
or expose it through `mhp-mcp` like any native MHP device.
"""
from .base import Action, BoundDriver, Setting, Signal, params_from_signature

__all__ = ["Action", "BoundDriver", "Setting", "Signal", "params_from_signature"]
