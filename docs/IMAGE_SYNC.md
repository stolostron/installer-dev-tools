# Container Image Sync

This repository includes a GitHub Action workflow that automatically syncs container images from source to target registries on a weekly schedule.

## Configuration

### Image Sync Config

Edit `config/image-sync.yaml` to define which images to sync:

```yaml
images:
  - source: quay.io/source-org/image-name
    target: quay.io/target-org/image-name
    tag: v1.0.0
```

You can add as many images as needed to the `images` list.

### GitHub Secrets

Configure the following secrets in your GitHub repository settings (Settings > Secrets and variables > Actions):

- `SOURCE_REGISTRY_USER`: Username for the source quay.io registry
- `SOURCE_REGISTRY_PASSWORD`: Password or token for the source registry
- `TARGET_REGISTRY_USER`: Username for the target quay.io registry
- `TARGET_REGISTRY_PASSWORD`: Password or token for the target registry

If source and target use the same credentials, you can set them to the same values.

## Schedule

The workflow runs automatically:
- **Weekly**: Every Monday at 2:00 AM UTC
- **Manual**: Can be triggered manually via GitHub Actions UI

To change the schedule, edit the cron expression in `.github/workflows/sync-images.yml`:

```yaml
schedule:
  - cron: '0 2 * * 1'  # Minute Hour Day Month DayOfWeek
```

Common cron schedules:
- `0 2 * * 1` - Every Monday at 2:00 AM
- `0 2 * * 0` - Every Sunday at 2:00 AM
- `0 2 1 * *` - First day of every month at 2:00 AM
- `0 2 */7 * *` - Every 7 days at 2:00 AM

## Manual Execution

To manually trigger the image sync:

1. Go to the "Actions" tab in GitHub
2. Select "Sync Container Images" workflow
3. Click "Run workflow"
4. Choose the branch and click "Run workflow"

## How It Works

1. Workflow checks out the repository
2. Authenticates to both source and target registries using podman
3. Reads `config/image-sync.yaml` using yq
4. For each image:
   - Pulls from source registry
   - Tags for target registry
   - Pushes to target registry
   - Cleans up local images
5. Logs out from registries

## Troubleshooting

### Authentication Failures

Ensure your secrets are correctly set and have the necessary permissions:
- For quay.io: Use a robot account or user account with pull/push permissions
- Verify the secret names match exactly: `SOURCE_REGISTRY_USER`, `SOURCE_REGISTRY_PASSWORD`, etc.

### Workflow Not Running

- Check the "Actions" tab to see if workflows are enabled for the repository
- Verify the cron schedule syntax is correct
- Note: GitHub Actions may delay scheduled workflows by a few minutes during high load

### Image Pull/Push Failures

- Verify the image exists at the source location
- Check that the credentials have permission to pull from source and push to target
- Ensure the repository exists at the target location (may need to create it first)
