import json
from bridge.reply import Reply, ReplyType
from config import conf


def get_info(workflow, context):
    work_res = workflow.coze_client.workflows.runs.create(workflow_id=workflow.current_flow_id, parameters={}, bot_id=workflow.bot_id)

    if isinstance(work_res.data, str):
        try:
            obj = json.loads(work_res.data)

            news = obj.get("news")
            output = obj.get("output")
            if news and len(news) > 0:
                for new in news:
                    context.kwargs.get("channel").send(Reply(ReplyType.LINK, new), context)
            elif output:
                context.kwargs.get("channel").send(Reply(ReplyType.TEXT, output), context)

            return True
        except Exception as e:
            context.kwargs.get("channel").send(Reply(ReplyType.TEXT, "工作流执行失败"), context)
            return False

    context.kwargs.get("channel").send(Reply(ReplyType.TEXT, "工作流执行结果转换失败"), context)
    return False


def _default_output(workflow, context, pending_text):
    if pending_text:
        context.kwargs.get("channel").send(Reply(ReplyType.TEXT, pending_text), context)

    work_res = workflow.coze_client.workflows.runs.create(workflow_id=workflow.current_flow_id, parameters={}, bot_id=workflow.bot_id)

    if isinstance(work_res.data, str):
        try:
            obj = json.loads(work_res.data)
            output = obj.get("output")
            if output:
                context.kwargs.get("channel").send(Reply(ReplyType.TEXT, output), context)

            return True
        except Exception as e:
            context.kwargs.get("channel").send(Reply(ReplyType.TEXT, "工作流执行失败"), context)
            return False

    context.kwargs.get("channel").send(Reply(ReplyType.TEXT, "工作流执行结果转换失败"), context)
    return False
