import os

import aws_cdk as cdk

from infra.infra_stack import InfraStack

app = cdk.App()
InfraStack(
    app,
    "FraudDetectionStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)
app.synth()