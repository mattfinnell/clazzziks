import * as aws from '@pulumi/aws';
import { stack, tags, config, firebaseEnabled } from '../config';

export interface Secrets {
  firebaseSecret?: aws.secretsmanager.Secret;
  adminEmailSecret?: aws.secretsmanager.Secret;
}

// Optional Secrets Manager entries. Each is seeded from a Pulumi secret; the
// value stays encrypted in stack state and is fetched onto the box at boot,
// never baked into the image or user data.
export function createSecrets(): Secrets {
  let firebaseSecret: aws.secretsmanager.Secret | undefined;
  if (firebaseEnabled) {
    firebaseSecret = new aws.secretsmanager.Secret('firebase-creds', {
      description: `clazzziks-${stack} Firebase service-account JSON`,
      tags,
    });
    new aws.secretsmanager.SecretVersion('firebase-creds-v', {
      secretId: firebaseSecret.id,
      secretString: config.firebaseCredentials!,
    });
  }

  let adminEmailSecret: aws.secretsmanager.Secret | undefined;
  if (config.adminEmail !== undefined) {
    adminEmailSecret = new aws.secretsmanager.Secret('admin-email', {
      description: `clazzziks-${stack} admin email (DB owner seed)`,
      tags,
    });
    new aws.secretsmanager.SecretVersion('admin-email-v', {
      secretId: adminEmailSecret.id,
      secretString: config.adminEmail,
    });
  }

  return { firebaseSecret, adminEmailSecret };
}
