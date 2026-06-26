import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';
import { tags } from '../config';

export interface Iam {
  instanceRole: aws.iam.Role;
  instanceProfile: aws.iam.InstanceProfile;
}

// The instance pulls the Docker image from ECR and reads its secrets at boot.
// SSMManagedInstanceCore enables Session Manager shell access (no SSH keys needed).
export function createIam(
  masterSecretArn: pulumi.Input<string>,
  firebaseSecret?: aws.secretsmanager.Secret,
  adminEmailSecret?: aws.secretsmanager.Secret,
): Iam {
  const instanceRole = new aws.iam.Role('instance-role', {
    assumeRolePolicy: aws.iam.assumeRolePolicyForPrincipal({ Service: 'ec2.amazonaws.com' }),
    managedPolicyArns: [
      'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly',
      'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
    ],
    tags,
  });

  const instanceProfile = new aws.iam.InstanceProfile('instance-profile', {
    role: instanceRole.name,
  });

  // Allow the instance to read exactly its DB secret (and Firebase/admin secrets).
  const secretArns: pulumi.Input<string>[] = [masterSecretArn];
  if (firebaseSecret) secretArns.push(firebaseSecret.arn);
  if (adminEmailSecret) secretArns.push(adminEmailSecret.arn);

  new aws.iam.RolePolicy('instance-secrets-policy', {
    role: instanceRole.id,
    policy: pulumi.all(secretArns).apply(arns =>
      JSON.stringify({
        Version: '2012-10-17',
        Statement: [{
          Effect: 'Allow',
          Action: ['secretsmanager:GetSecretValue'],
          Resource: arns,
        }],
      })
    ),
  });

  return { instanceRole, instanceProfile };
}
