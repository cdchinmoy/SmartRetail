from celery import Celery
from app.core.config import settings
from app.billing.worker import sweep

celery=Celery('smartretail',broker=settings.redis_url)
celery.conf.update(timezone='UTC',task_ignore_result=True,beat_schedule={'billing-outbox-and-expiry':{'task':'billing.sweep','schedule':30.0}})
@celery.task(name='billing.sweep')
def billing_sweep():
    sweep()
