import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';
import * as awsx from '@pulumi/awsx';
import { stack, tags, config } from '../config';

export interface Compute {
  instance: aws.ec2.Instance;
  eip: aws.ec2.Eip;
}

export interface ComputeArgs {
  vpc: awsx.ec2.Vpc;
  instanceSg: aws.ec2.SecurityGroup;
  instanceProfile: aws.iam.InstanceProfile;
  userData: pulumi.Input<string>;
}

// EC2 instance (Amazon Linux 2023) running the backend container, fronted by an
// Elastic IP so CloudFront has a stable origin DNS name.
export function createCompute(args: ComputeArgs): Compute {
  const { vpc, instanceSg, instanceProfile, userData } = args;

  const ami = aws.ec2.getAmiOutput({
    mostRecent: true,
    owners: ['amazon'],
    filters: [
      { name: 'name',         values: ['al2023-ami-*-x86_64'] },
      { name: 'architecture', values: ['x86_64'] },
    ],
  });

  const instance = new aws.ec2.Instance('instance', {
    ami: ami.id,
    instanceType: config.instanceType,
    subnetId: vpc.publicSubnetIds.apply(ids => ids[0]),
    vpcSecurityGroupIds: [instanceSg.id],
    iamInstanceProfile: instanceProfile.name,
    userData,
    // User-data only runs on first boot, so any change to it (e.g. enabling
    // Firebase, new env vars) must roll a fresh instance to take effect.
    userDataReplaceOnChange: true,
    ebsBlockDevices: [{
      deviceName: '/dev/xvdf',
      volumeSize: 50,
      volumeType: 'gp3',
      deleteOnTermination: true,
    }],
    tags: { ...tags, Name: `clazzziks-${stack}` },
  });

  const eip = new aws.ec2.Eip('eip', { tags });
  new aws.ec2.EipAssociation('eip-assoc', {
    instanceId: instance.id,
    allocationId: eip.id,
  });

  return { instance, eip };
}
