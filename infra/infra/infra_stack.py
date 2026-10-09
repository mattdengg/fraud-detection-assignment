from pathlib import Path

from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from aws_cdk.aws_ecr_assets import Platform
from aws_cdk import CfnOutput, Duration, RemovalPolicy
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_sqs as sqs
from constructs import Construct

API_DIR = Path(__file__).resolve().parents[2] / "api"

class InfraStack(Stack):
    """Fraud detection system: API on Fargate behind an ALB."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Public subnets only, no NAT gateway (cost tradeoff, see README)
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        # --- Messaging ---
        dlq = sqs.Queue(
            self,
            "FlaggedDLQ",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )
        queue = sqs.Queue(
            self,
            "FlaggedQueue",
            visibility_timeout=Duration.seconds(60),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3),
        )

        # --- Storage ---
        activity_table = dynamodb.Table(
            self,
            "AccountActivity",
            partition_key=dynamodb.Attribute(name="account_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.DESTROY,
        )
        transactions_table = dynamodb.Table(
            self,
            "Transactions",
            partition_key=dynamodb.Attribute(name="transaction_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "ApiService",
            cluster=cluster,
            cpu=256,
            memory_limit_mib=512,
            desired_count=1,
            min_healthy_percent=100,
            public_load_balancer=True,
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    str(API_DIR), platform=Platform.LINUX_ARM64
                ),
                container_port=8000,
                environment={
                    "LARGE_WITHDRAWAL_THRESHOLD": "5000",
                    "FAILED_LOGIN_LIMIT": "3",
                    "FAILED_LOGIN_WINDOW_MINUTES": "15",
                    "ACCOUNT_ACTIVITY_TABLE": activity_table.table_name,
                    "TRANSACTIONS_TABLE": transactions_table.table_name,
                    "FLAGGED_QUEUE_URL": queue.queue_url,
                },
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="api",
                    log_retention=logs.RetentionDays.ONE_WEEK,
                ),
            ),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )

        service.target_group.configure_health_check(
            path="/health", healthy_http_codes="200"
        )

        # --- Least-privilege IAM for the API task ---
        task_role = service.task_definition.task_role
        activity_table.grant_read_write_data(task_role)
        transactions_table.grant_read_write_data(task_role)
        queue.grant_send_messages(task_role)

        CfnOutput(self, "FlaggedQueueUrl", value=queue.queue_url)
        CfnOutput(self, "AccountActivityTableName", value=activity_table.table_name)
        CfnOutput(self, "TransactionsTableName", value=transactions_table.table_name)