import os
from config import autoclean

async def auto_clean(popped):
    try:
        if not popped:
            return
        rem = popped.get("file")
        if not rem:
            return
        
        if rem in autoclean:
            autoclean.remove(rem)
        
        count = autoclean.count(rem)
        if count == 0:
            if "vid_" not in rem and "live_" not in rem and "index_" not in rem:
                try:
                    if os.path.exists(rem):
                        os.remove(rem)
                except Exception:
                    pass
    except Exception:
        pass


async def clear_queue_files(chat_id, queue):
    if not queue:
        return
    
    for item in queue:
        await auto_clean(item)
