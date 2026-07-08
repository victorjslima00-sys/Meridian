import logging
import schedule
import time
from typing import Callable

logger = logging.getLogger(__name__)

class Scheduler:
    """Wrapper para o schedule, roda as tarefas no horario especificado"""
    def __init__(self):
        self._running = False
        
    def add_daily_job(self, time_str: str, job_func: Callable):
        schedule.every().day.at(time_str).do(job_func)
        logger.info("Job added for %s", time_str)
        
    def run_pending(self):
        schedule.run_pending()
        
    def start_blocking(self):
        self._running = True
        logger.info("Scheduler started.")
        while self._running:
            self.run_pending()
            time.sleep(60)
            
    def stop(self):
        self._running = False
