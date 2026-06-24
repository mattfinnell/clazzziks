import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';

export interface EnvConfig {
  readonly envName: string;
  /** EC2 instance type — t3.micro for staging, t3.small for production. */
  readonly instanceType: ec2.InstanceType;
  /** DESTROY lets `cdk destroy` clean up fully; use RETAIN in production. */
  readonly removalPolicy: cdk.RemovalPolicy;
  /** Must be false when removalPolicy is RETAIN. */
  readonly autoDeleteObjects: boolean;
}

export const STAGING: EnvConfig = {
  envName: 'staging',
  instanceType: new ec2.InstanceType('t3.micro'),
  removalPolicy: cdk.RemovalPolicy.DESTROY,
  autoDeleteObjects: true,
};

export const PRODUCTION: EnvConfig = {
  envName: 'production',
  instanceType: new ec2.InstanceType('t3.small'),
  removalPolicy: cdk.RemovalPolicy.RETAIN,
  autoDeleteObjects: false,
};
