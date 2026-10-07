import os
import asyncio
import logging
from time import time
from aiohttp import ClientSession

from bot import (
    task_dict,
    task_dict_lock,
    queued_dl,
    queued_up,
    non_queued_dl,
    non_queued_up,
    LOGGER,
    bot_start_time
)

# Default timeout 5 minutes (300 seconds)
IDLE_TIMEOUT = int(os.environ.get("WZML_X_IDLE_TIMEOUT", "300"))

NORTHFLANK_API_TOKEN = os.environ.get("NORTHFLANK_API_TOKEN", "")
NORTHFLANK_PROJECT_ID = os.environ.get("NORTHFLANK_PROJECT_ID", "")
NORTHFLANK_SERVICE_ID = os.environ.get("NORTHFLANK_SERVICE_ID", "")

async def scale_to_zero():
    if not all([NORTHFLANK_API_TOKEN, NORTHFLANK_PROJECT_ID, NORTHFLANK_SERVICE_ID]):
        LOGGER.error("Missing Northflank API credentials. Cannot scale to zero.")
        return False
        
    url = f"https://api.northflank.com/v1/projects/{NORTHFLANK_PROJECT_ID}/services/combined/{NORTHFLANK_SERVICE_ID}"
    headers = {
        "Authorization": f"Bearer {NORTHFLANK_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"deployment": {"instances": 0}}
    
    try:
        LOGGER.info("Scaling WZML-X from 1 to 0")
        async with ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as response:
                if response.status in [200, 201, 202, 204]:
                    LOGGER.info("Northflank scale request succeeded. WZML-X scaled to 0")
                    return True
                else:
                    LOGGER.error(f"Failed to scale down. Status: {response.status}")
                    return False
    except Exception as e:
        LOGGER.error(f"Error during scale to zero request: {e}")
        return False

async def check_idle_loop():
    if IDLE_TIMEOUT <= 0:
        LOGGER.info("Idle timeout is disabled.")
        return
        
    # Wait for the startup grace period to finish
    while time() - bot_start_time < 60:
        await asyncio.sleep(5)
        
    idle_start_time = None
    
    while True:
        await asyncio.sleep(10)
        
        async with task_dict_lock:
            # Determine if there's any active work
            is_active = (
                len(task_dict) > 0 or
                len(queued_dl) > 0 or
                len(queued_up) > 0 or
                len(non_queued_dl) > 0 or
                len(non_queued_up) > 0
            )
            
        if is_active:
            if idle_start_time is not None:
                LOGGER.info("WZML-X is active again. Resetting idle timer.")
            idle_start_time = None
        else:
            if idle_start_time is None:
                idle_start_time = time()
                LOGGER.info(f"WZML-X is idle. Timer started: {IDLE_TIMEOUT}s")
            else:
                elapsed = time() - idle_start_time
                if elapsed >= IDLE_TIMEOUT:
                    LOGGER.info(f"WZML-X idle timeout reached for {elapsed:.2f}s.")
                    # Scale to zero
                    success = await scale_to_zero()
                    if success:
                        LOGGER.info("Idle manager stopping after successful scale-to-zero request.")
                        return

_idle_task = None

def start_idle_manager():
    global _idle_task
    from bot import bot_loop
    _idle_task = bot_loop.create_task(check_idle_loop())
