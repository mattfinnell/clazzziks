import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';
import * as awsx from '@pulumi/awsx';
import { stack, tags, config } from '../config';

export interface Database {
  db: aws.rds.Instance;
  masterSecretArn: pulumi.Output<string>;
}

// manageMasterUserPassword=true → RDS generates the password and stores/rotates
// it in Secrets Manager. No password ever lives in Pulumi state or user data;
// the instance reads it at boot via its IAM role.
export function createDatabase(vpc: awsx.ec2.Vpc, dbSg: aws.ec2.SecurityGroup): Database {
  const dbSubnets = new aws.rds.SubnetGroup('db-subnets', {
    subnetIds: vpc.publicSubnetIds,
    tags,
  });

  const db = new aws.rds.Instance('db', {
    engine: 'postgres',
    engineVersion: '16',
    instanceClass: config.dbInstanceClass,
    allocatedStorage: config.dbAllocatedStorage,
    storageType: 'gp3',
    dbName: 'clazzziks',
    username: 'clazzziks',
    manageMasterUserPassword: true,
    dbSubnetGroupName: dbSubnets.name,
    vpcSecurityGroupIds: [dbSg.id],
    publiclyAccessible: false,
    multiAz: false,
    backupRetentionPeriod: config.dbBackupRetentionDays,
    deletionProtection: config.dbDeletionProtection,
    skipFinalSnapshot: !config.retainBucket,
    finalSnapshotIdentifier: config.retainBucket ? `clazzziks-${stack}-final` : undefined,
    applyImmediately: true,
    tags,
  });

  // ARN of the RDS-managed master password secret.
  const masterSecretArn = db.masterUserSecrets.apply(s => s[0].secretArn);

  return { db, masterSecretArn };
}
