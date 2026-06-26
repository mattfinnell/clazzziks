import * as aws from '@pulumi/aws';
import * as awsx from '@pulumi/awsx';
import { stack, tags } from '../config';

export interface Network {
  vpc: awsx.ec2.Vpc;
  instanceSg: aws.ec2.SecurityGroup;
  dbSg: aws.ec2.SecurityGroup;
}

// Two public subnets (no NAT gateway — the instance egresses via Elastic IP).
// RDS requires a DB subnet group spanning >= 2 AZs, hence two AZs here. RDS is
// not publicly accessible, so it stays internal despite the public subnets.
export function createNetwork(): Network {
  const vpc = new awsx.ec2.Vpc('vpc', {
    numberOfAvailabilityZones: 2,
    natGateways: { strategy: 'None' },
    subnetSpecs: [{ type: 'Public', cidrMask: 24 }],
    // Pin the allocation strategy: awsx's default flips Legacy → Auto in the next
    // major. Setting it now (pre-deploy) avoids a forced subnet replacement later.
    subnetStrategy: 'Auto',
    tags,
  });

  const instanceSg = new aws.ec2.SecurityGroup('instance-sg', {
    vpcId: vpc.vpcId,
    description: `clazzziks-${stack} instance`,
    egress: [{ fromPort: 0, toPort: 0, protocol: '-1', cidrBlocks: ['0.0.0.0/0'], description: 'all outbound' }],
    ingress: [
      { fromPort: 80,  toPort: 80,  protocol: 'tcp', cidrBlocks: ['0.0.0.0/0'], description: 'HTTP' },
      { fromPort: 443, toPort: 443, protocol: 'tcp', cidrBlocks: ['0.0.0.0/0'], description: 'HTTPS' },
    ],
    tags,
  });

  // Postgres reachable only from the EC2 instance — never from the internet.
  const dbSg = new aws.ec2.SecurityGroup('db-sg', {
    vpcId: vpc.vpcId,
    description: `clazzziks-${stack} postgres`,
    egress: [{ fromPort: 0, toPort: 0, protocol: '-1', cidrBlocks: ['0.0.0.0/0'], description: 'all outbound' }],
    ingress: [
      { fromPort: 5432, toPort: 5432, protocol: 'tcp', securityGroups: [instanceSg.id], description: 'Postgres from instance' },
    ],
    tags,
  });

  return { vpc, instanceSg, dbSg };
}
