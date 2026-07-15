"""
Tools for the Cloud Ops agent. AWS tools are built PER authenticated session so
they run with the signed-in user's boto3 credentials — each user sees only their
own account. All tools are read-only (Phase 1); mutating actions come later
behind a confirmation gate.
"""
from botocore.exceptions import ClientError, BotoCoreError
from langchain_core.tools import StructuredTool
from langgraph.types import interrupt


def _err(service, e):
    if isinstance(e, ClientError):
        err = e.response.get("Error", {})
        return f"{service} error: {err.get('Code', 'Error')} — {err.get('Message', str(e))}"
    if isinstance(e, BotoCoreError):
        return f"{service} error: {e}"
    return f"{service} error: {e}"


def execute_ec2_action(boto_session, region, action, instance_id):
    """Actually run a start/stop/reboot. Called by the backend ONLY after the user confirms."""
    ec2 = boto_session.client("ec2", region_name=region)
    try:
        if action == "start":
            ec2.start_instances(InstanceIds=[instance_id])
        elif action == "stop":
            ec2.stop_instances(InstanceIds=[instance_id])
        elif action == "reboot":
            ec2.reboot_instances(InstanceIds=[instance_id])
        else:
            return f"Unknown action '{action}'."
        return f"Done — {action} initiated for {instance_id}."
    except Exception as e:  # noqa: BLE001
        return _err("EC2", e)


def build_tools(boto_session, region, search_runbooks_fn, allow_mutations=False):
    """Return the tool list bound to this session's AWS credentials + shared runbook search.

    Mutating tools (start/stop/reboot) are included only when allow_mutations is
    True. They call LangGraph's interrupt() to pause the graph for confirmation;
    the backend resumes with the user's decision and only then does the action run.
    """
    ec2 = boto_session.client("ec2", region_name=region)
    s3 = boto_session.client("s3")
    ddb = boto_session.client("dynamodb", region_name=region)
    cw = boto_session.client("cloudwatch", region_name=region)

    def _instance_rows(filters=None):
        kwargs = {"Filters": filters} if filters else {}
        rows = []
        for reservation in ec2.describe_instances(**kwargs).get("Reservations", []):
            for inst in reservation.get("Instances", []):
                name = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), "")
                rows.append(
                    {
                        "id": inst["InstanceId"],
                        "name": name,
                        "type": inst.get("InstanceType"),
                        "state": inst.get("State", {}).get("Name"),
                        "az": inst.get("Placement", {}).get("AvailabilityZone"),
                        "private_ip": inst.get("PrivateIpAddress"),
                        "public_ip": inst.get("PublicIpAddress"),
                    }
                )
        return rows

    def list_aws_resources() -> str:
        """Summarize the AWS resources in the account: counts of EC2 instances (total/running), S3 buckets, and DynamoDB tables. Use when the user asks what is running or what resources are available."""
        parts = []
        try:
            rows = _instance_rows()
            running = sum(1 for r in rows if r["state"] == "running")
            parts.append(f"EC2: {len(rows)} instance(s), {running} running")
        except Exception as e:  # noqa: BLE001
            parts.append(_err("EC2", e))
        try:
            parts.append(f"S3: {len(s3.list_buckets().get('Buckets', []))} bucket(s)")
        except Exception as e:  # noqa: BLE001
            parts.append(_err("S3", e))
        try:
            parts.append(f"DynamoDB: {len(ddb.list_tables().get('TableNames', []))} table(s) in {region}")
        except Exception as e:  # noqa: BLE001
            parts.append(_err("DynamoDB", e))
        return "\n".join(parts)

    def list_ec2_instances(state: str = "") -> str:
        """List EC2 instances with details (id, name, type, state, availability zone, private/public IP). Optionally filter by state such as 'running' or 'stopped'."""
        try:
            filters = [{"Name": "instance-state-name", "Values": [state]}] if state else None
            rows = _instance_rows(filters)
            if not rows:
                return "No EC2 instances found."
            return "\n".join(
                f"- {r['id']} ({r['name'] or 'unnamed'}): {r['state']}, {r['type']}, {r['az']}, "
                f"private={r['private_ip']}, public={r['public_ip']}"
                for r in rows
            )
        except Exception as e:  # noqa: BLE001
            return _err("EC2", e)

    def get_ec2_health(instance_id: str = "") -> str:
        """Report EC2 instance health/status checks (system status and instance status). Optionally for one instance id; otherwise all instances."""
        try:
            kwargs = {"IncludeAllInstances": True}
            if instance_id:
                kwargs["InstanceIds"] = [instance_id]
            statuses = ec2.describe_instance_status(**kwargs).get("InstanceStatuses", [])
            if not statuses:
                return "No instance status information found."
            return "\n".join(
                f"- {s['InstanceId']}: state={s['InstanceState']['Name']}, "
                f"system={s['SystemStatus']['Status']}, instance={s['InstanceStatus']['Status']}"
                for s in statuses
            )
        except Exception as e:  # noqa: BLE001
            return _err("EC2", e)

    def list_s3_buckets() -> str:
        """List the S3 buckets in the account with their creation dates."""
        try:
            buckets = s3.list_buckets().get("Buckets", [])
            if not buckets:
                return "No S3 buckets found."
            return "\n".join(f"- {b['Name']} (created {b['CreationDate']:%Y-%m-%d})" for b in buckets)
        except Exception as e:  # noqa: BLE001
            return _err("S3", e)

    def list_dynamodb_tables() -> str:
        """List the DynamoDB tables in the account for the configured region."""
        try:
            tables = ddb.list_tables().get("TableNames", [])
            return "\n".join(f"- {t}" for t in tables) if tables else "No DynamoDB tables found."
        except Exception as e:  # noqa: BLE001
            return _err("DynamoDB", e)

    def get_cloudwatch_alarms(state: str = "ALARM") -> str:
        """List CloudWatch alarms, optionally filtered by state ('ALARM', 'OK', 'INSUFFICIENT_DATA', or '' for all). Use this for health checks and diagnosis."""
        try:
            kwargs = {"StateValue": state} if state else {}
            alarms = cw.describe_alarms(**kwargs).get("MetricAlarms", [])
            if not alarms:
                return f"No CloudWatch alarms in state '{state or 'any'}'."
            return "\n".join(
                f"- {a['AlarmName']}: {a['StateValue']} (metric {a.get('MetricName', '?')}, "
                f"{a.get('Namespace', '?')})"
                for a in alarms
            )
        except Exception as e:  # noqa: BLE001
            return _err("CloudWatch", e)

    def search_runbooks(query: str) -> str:
        """Search the internal ops runbooks / knowledge base for procedures, policies and how-tos (deployments, incidents, databases, scaling, monitoring, access)."""
        return search_runbooks_fn(query)

    read_funcs = (
        list_aws_resources,
        list_ec2_instances,
        get_ec2_health,
        get_cloudwatch_alarms,
        list_s3_buckets,
        list_dynamodb_tables,
        search_runbooks,
    )

    # --- Mutating tools: pause via interrupt(), execute only after confirmation ---
    def _describe(instance_id):
        for reservation in ec2.describe_instances(InstanceIds=[instance_id]).get("Reservations", []):
            for inst in reservation.get("Instances", []):
                name = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), "")
                return {"name": name, "state": inst.get("State", {}).get("Name")}
        return None

    def _act(action, instance_id):
        try:
            info = _describe(instance_id)
        except Exception as e:  # noqa: BLE001
            return _err("EC2", e)
        if not info:
            return f"No EC2 instance found with id {instance_id}."

        # Pause the graph for a human decision. Resumes with the value the backend
        # passes to Command(resume=...): {"confirmed": bool}.
        decision = interrupt(
            {
                "type": "confirm_action",
                "action": action,
                "instance_id": instance_id,
                "name": info["name"],
                "state": info["state"],
                "prompt": (
                    f"Confirm {action.upper()} of {instance_id} "
                    f"(name '{info['name'] or 'unnamed'}', currently {info['state']})? "
                    "Reply 'confirm' to proceed, or anything else to cancel."
                ),
            }
        )
        if isinstance(decision, dict) and decision.get("confirmed"):
            return execute_ec2_action(boto_session, region, action, instance_id)
        return f"Cancelled — did not {action} {instance_id}."

    def start_ec2_instance(instance_id: str) -> str:
        """Start an EC2 instance. Pauses for the user to confirm before it runs."""
        return _act("start", instance_id)

    def stop_ec2_instance(instance_id: str) -> str:
        """Stop an EC2 instance. Pauses for the user to confirm before it runs."""
        return _act("stop", instance_id)

    def reboot_ec2_instance(instance_id: str) -> str:
        """Reboot/restart an EC2 instance. Pauses for the user to confirm before it runs."""
        return _act("reboot", instance_id)

    funcs = read_funcs
    if allow_mutations:
        funcs = read_funcs + (start_ec2_instance, stop_ec2_instance, reboot_ec2_instance)

    return [StructuredTool.from_function(f) for f in funcs]
