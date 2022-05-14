import boto3
import logging
from datetime import datetime, timedelta, timezone, tzinfo
logging.basicConfig(level='INFO')
log = logging.getLogger()
log.setLevel(logging.INFO)

ec2_client = boto3.client('ec2')

def lambda_handler(event, context):
    retain_days = event.get('retain_days', None)
    dt = datetime.now(timezone.utc).astimezone()
    log.info(f"Current timestamp: {dt.isoformat()}")
    dt_delete = dt - timedelta(days=int(retain_days))
    log.info(f"Deletion timestamp: {dt_delete.isoformat()}")
    ami_list = ec2_client.describe_images(
        Owners=['self'],
        Filters=[
            {
                'Name': 'tag-key',
                'Values': ['patching-timestamp']
            }
        ]
    )
    
    log.debug(ami_list)
    if len(ami_list.get('Images', [])) == 0: 
        log.info("No patching AMIs were returned.")
        return {}   
    for ami in ami_list['Images']:
        try:
            snapshots = []
            log.info(f'AMI: {ami["ImageId"]}')
            patching_timestamp = [tag['Value'] for tag in ami['Tags'] if tag['Key'] == 'patching-timestamp'][0]
            patching_timestamp = datetime.fromisoformat(patching_timestamp)
            if patching_timestamp.tzinfo is None:
                patching_timestamp = patching_timestamp.replace(tzinfo=timezone.utc).astimezone()
            log.info(f'patching-timestamp: {patching_timestamp}')
            if patching_timestamp < dt_delete:
                log.info (f'AMI {ami["ImageId"]} will be de-registered')
                snapshots = [block_device_mapping.get("Ebs",{}).get("SnapshotId", None) for block_device_mapping in ami["BlockDeviceMappings"]]
                log.info(f'Snapshots to delete: {snapshots}')
                log.info(f'De-registering AMI {ami["ImageId"]}')
                ec2_client.deregister_image(ImageId=ami["ImageId"])
                for snapshot in snapshots:
                    try:
                        log.info (f'Deleting AMI snapshot {snapshot}')
                        ec2_client.delete_snapshot(SnapshotId=snapshot)
                    except Exception as ex:
                        log.exception(ex)                 
        except Exception as ex:        
            log.exception(ex)
    # Attempt to cleanup any orphaned patching snapshots
    paginated_snaps = ec2_client.get_paginator('describe_snapshots').paginate(
        Filters=[
            {
                'Name': 'tag-key',
                'Values': ['patching-timestamp']
            }
        ]
    )
    for page in paginated_snaps:
        for snapshot in page['Snapshots']:
            try: 
                log.info(snapshot)
                log.debug(f'Snapshot: {snapshot["SnapshotId"]}')
                patching_timestamp = [tag['Value'] for tag in snapshot['Tags'] if tag['Key'] == 'patching-timestamp'][0]
                patching_timestamp = datetime.fromisoformat(patching_timestamp)        
                if patching_timestamp.tzinfo is None:
                    patching_timestamp = patching_timestamp.replace(tzinfo=timezone.utc).astimezone()
                log.info(f'patching-timestamp: {patching_timestamp}')
                if patching_timestamp < dt_delete:
                    log.info (f'Deleting AMI snapshot {snapshot["SnapshotId"]}')
                    ec2_client.delete_snapshot(SnapshotId=snapshot["SnapshotId"])                                        
            except Exception as ex:        
                log.exception(ex)
    