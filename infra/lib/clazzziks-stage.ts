import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { ClazzzikStack } from './clazzziks-stack';
import { EnvConfig } from './config';

export class ClazzzikStage extends cdk.Stage {
  constructor(scope: Construct, id: string, config: EnvConfig, props?: cdk.StageProps) {
    super(scope, id, props);
    new ClazzzikStack(this, 'Clazzziks', { config });
  }
}
