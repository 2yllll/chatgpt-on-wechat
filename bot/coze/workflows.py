from typing import Dict
from config import conf
import json
from bridge.reply import Reply, ReplyType
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED
from concurrent.futures import ProcessPoolExecutor
import bot.coze.schedulerFn as schedulerFn
import datetime


class Workflow:
    def __init__(self, coze):
        self.coze_client = coze
        self.workflows: Dict[str, str] = conf().get("workflows")
        self._base_url = conf().get("coze_api_base")
        self.current_flow_id = None
        self.scheduler = BackgroundScheduler(daemon=True, executor=ProcessPoolExecutor(max_workers=5), timezone="Asia/Shanghai")
        self.scheduler.add_listener(self._timer_executed, mask=EVENT_JOB_EXECUTED)
        self.scheduler.start()

    def _get_workflow(self, match: str):
        flow: Dict[str, list] or None = self.workflows[match]
        if flow is None:
            self.current_flow_id = None
        else:
            self.current_flow_id = flow[0]
        return flow

    def _call_workflow(self, context):
        if context is None:
            return Reply(ReplyType.TEXT, "执行失败")
        

        workflow = self.coze_client.workflows.runs.create(
            workflow_id=self.current_flow_id,
        )

        if isinstance(workflow.data, str):
            try:
                obj = json.loads(workflow.data)
                output = obj.get("output")
                if output:
                    return Reply(ReplyType.TEXT, output)
            except Exception as e:
                return Reply(ReplyType.TEXT, "工作流执行失败")

        return Reply(ReplyType.TEXT, "工作流执行结果转换失败")

    def apply(self, match: str, context):
        flow_id, pending_text = self._get_workflow(match)
        if flow_id != "":
            context.kwargs.get("channel").send(Reply(ReplyType.TEXT, pending_text if pending_text else "正在执行工作流，请稍等..."), context)
            return self._call_workflow(context)
        else:
            return Reply(ReplyType.TEXT, "未找到相关工作流，请查看配置文件。")

    def timer_trigger(self, match: str, context, **kwargs):
        flow_id, pending_text = self._get_workflow(match)
        if flow_id != "":
            if self.scheduler.get_job(match):
                # context.kwargs.get("channel").send(Reply(ReplyType.TEXT, f"{fn_name}已经开启了，无需再开启。"), context)
                self.scheduler.pause_job(match)
                self.scheduler.remove_job(match)
                return Reply(ReplyType.TEXT, f"关闭{match}。")
            fn = None
            try:
                fn = getattr(schedulerFn, f"{match}")
            except:
                fn = schedulerFn._default_output

            if not fn:
                return Reply(ReplyType.TEXT, f"{match}启用失败")

            self.scheduler.add_job(fn, "cron", **kwargs, id=f"{match}", args=[self, context, pending_text], timezone="Asia/Shanghai")

            return Reply(ReplyType.TEXT, f"{match}已启用 {json.dumps(kwargs)}")

    def _timer_executed(self, event):
        if event.code == EVENT_JOB_EXECUTED:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"{now} 执行 {event.job_id}  结果：{event.retval}")
