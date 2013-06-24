# The test cases in this file have been annotated for inventory.
# To extract the inventory (in csv format) use the command:
#
#   grep '^ *# TESTCASE' | sed 's/^ *# TESTCASE //'
#

from cStringIO import StringIO
import logging
import json

import boto.exception
import boto.s3.connection
import boto.s3.acl

import time

from teuthology import misc as teuthology

log = logging.getLogger(__name__)

def successful_ops(out):
    summary = out['summary']
    if len(summary) == 0:
        return 0
    entry = summary[0]
    return entry['total']['successful_ops']

def rgwadmin(ctx, client, cmd):
    log.info('radosgw-admin: %s' % cmd)
    testdir = teuthology.get_testdir(ctx)
    pre = [
        '{tdir}/adjust-ulimits'.format(tdir=testdir),
        'ceph-coverage'.format(tdir=testdir),
        '{tdir}/archive/coverage'.format(tdir=testdir),
        'radosgw-admin'.format(tdir=testdir),
        '--log-to-stderr',
        '--format', 'json',
        ]
    pre.extend(cmd)
    (remote,) = ctx.cluster.only(client).remotes.iterkeys()
    proc = remote.run(
        args=pre,
        check_status=False,
        stdout=StringIO(),
        stderr=StringIO(),
        )
    r = proc.exitstatus
    out = proc.stdout.getvalue()
    j = None
    if not r and out != '':
        try:
            j = json.loads(out)
            log.info(' json result: %s' % j)
        except ValueError:
            j = out
            log.info(' raw result: %s' % j)
    return (r, j)

def task(ctx, config):
    """
    Test radosgw-admin functionality against a running rgw instance.
    """
    assert config is None or isinstance(config, list) \
        or isinstance(config, dict), \
        "task s3tests only supports a list or dictionary for configuration"
    all_clients = ['client.{id}'.format(id=id_)
                   for id_ in teuthology.all_roles_of_type(ctx.cluster, 'client')]
    if config is None:
        config = all_clients
    if isinstance(config, list):
        config = dict.fromkeys(config)
    clients = config.keys()

    # just use the first client...
    client = clients[0];

    ##
    user1='foo'
    user2='fud'
    subuser1='foo:foo1'
    subuser2='foo:foo2'
    display_name1='Foo'
    display_name2='Fud'
    email='foo@foo.com'
    access_key='9te6NH5mcdcq0Tc5i8i1'
    secret_key='Ny4IOauQoL18Gp2zM7lC1vLmoawgqcYP/YGcWfXu'
    access_key2='p5YnriCv1nAtykxBrupQ'
    secret_key2='Q8Tk6Q/27hfbFSYdSkPtUqhqx1GgzvpXa4WARozh'
    swift_secret1='gpS2G9RREMrnbqlp29PP2D36kgPR1tm72n5fPYfL'
    swift_secret2='ri2VJQcKSYATOY6uaDUX7pxgkW+W1YmC6OCxPHwy'

    bucket_name='myfoo'

    # legend (test cases can be easily grep-ed out)
    # TESTCASE 'testname','object','method','operation','assertion'
    # TESTCASE 'info-nosuch','user','info','non-existent user','fails'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert err

    # TESTCASE 'create-ok','user','create','w/all valid info','succeeds'
    (err, out) = rgwadmin(ctx, client, [
            'user', 'create',
            '--uid', user1,
            '--display-name', display_name1,
            '--email', email,
            '--access-key', access_key,
            '--secret', secret_key,
            '--max-buckets', '4'
            ])
    assert not err

    # TESTCASE 'duplicate email','user','create','existing user email','fails'
    (err, out) = rgwadmin(ctx, client, [
            'user', 'create',
            '--uid', user2,
            '--display-name', display_name2,
            '--email', email,
            ])
    assert err

    # TESTCASE 'info-existing','user','info','existing user','returns correct info'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert not err
    assert out['user_id'] == user1
    assert out['email'] == email
    assert out['display_name'] == display_name1
    assert len(out['keys']) == 1
    assert out['keys'][0]['access_key'] == access_key
    assert out['keys'][0]['secret_key'] == secret_key
    assert not out['suspended']

    # TESTCASE 'suspend-ok','user','suspend','active user','succeeds'
    (err, out) = rgwadmin(ctx, client, ['user', 'suspend', '--uid', user1])
    assert not err

    # TESTCASE 'suspend-suspended','user','suspend','suspended user','succeeds w/advisory'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert not err
    assert out['suspended']

    # TESTCASE 're-enable','user','enable','suspended user','succeeds'
    (err, out) = rgwadmin(ctx, client, ['user', 'enable', '--uid', user1])
    assert not err

    # TESTCASE 'info-re-enabled','user','info','re-enabled user','no longer suspended'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert not err
    assert not out['suspended']

    # TESTCASE 'add-keys','key','create','w/valid info','succeeds'
    (err, out) = rgwadmin(ctx, client, [
            'key', 'create', '--uid', user1,
            '--access-key', access_key2, '--secret', secret_key2,
            ])
    assert not err

    # TESTCASE 'info-new-key','user','info','after key addition','returns all keys'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert not err
    assert len(out['keys']) == 2
    assert out['keys'][0]['access_key'] == access_key2 or out['keys'][1]['access_key'] == access_key2
    assert out['keys'][0]['secret_key'] == secret_key2 or out['keys'][1]['secret_key'] == secret_key2

    # TESTCASE 'rm-key','key','rm','newly added key','succeeds, key is removed'
    (err, out) = rgwadmin(ctx, client, [
            'key', 'rm', '--uid', user1,
            '--access-key', access_key2,
            ])
    assert not err
    assert len(out['keys']) == 1
    assert out['keys'][0]['access_key'] == access_key
    assert out['keys'][0]['secret_key'] == secret_key

    # TESTCASE 'add-swift-key','key','create','swift key','succeeds'
    subuser_access = 'full'
    subuser_perm = 'full-control'

    (err, out) = rgwadmin(ctx, client, [
            'subuser', 'create', '--subuser', subuser1,
            '--access', subuser_access
            ])
    assert not err

    # TESTCASE 'add-swift-key','key','create','swift key','succeeds'
    (err, out) = rgwadmin(ctx, client, [
            'subuser', 'modify', '--subuser', subuser1,
            '--secret', swift_secret1,
            '--key-type', 'swift',
            ])
    assert not err

    # TESTCASE 'subuser-perm-mask', 'subuser', 'info', 'test subuser perm mask durability', 'succeeds'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])

    assert out['subusers'][0]['permissions'] == subuser_perm

    # TESTCASE 'info-swift-key','user','info','after key addition','returns all keys'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert not err
    assert len(out['swift_keys']) == 1
    assert out['swift_keys'][0]['user'] == subuser1
    assert out['swift_keys'][0]['secret_key'] == swift_secret1

    # TESTCASE 'add-swift-subuser','key','create','swift sub-user key','succeeds'
    (err, out) = rgwadmin(ctx, client, [
            'subuser', 'create', '--subuser', subuser2,
            '--secret', swift_secret2,
            '--key-type', 'swift',
            ])
    assert not err

    # TESTCASE 'info-swift-subuser','user','info','after key addition','returns all sub-users/keys'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert not err
    assert len(out['swift_keys']) == 2
    assert out['swift_keys'][0]['user'] == subuser2 or out['swift_keys'][1]['user'] == subuser2
    assert out['swift_keys'][0]['secret_key'] == swift_secret2 or out['swift_keys'][1]['secret_key'] == swift_secret2

    # TESTCASE 'rm-swift-key1','key','rm','subuser','succeeds, one key is removed'
    (err, out) = rgwadmin(ctx, client, [
            'key', 'rm', '--subuser', subuser1,
            '--key-type', 'swift',
            ])
    assert not err
    assert len(out['swift_keys']) == 1

    # TESTCASE 'rm-subuser','subuser','rm','subuser','success, subuser is removed'
    (err, out) = rgwadmin(ctx, client, [
            'subuser', 'rm', '--subuser', subuser1,
            ])
    assert not err
    assert len(out['subusers']) == 1

    # TESTCASE 'rm-subuser-with-keys','subuser','rm','subuser','succeeds, second subser and key is removed'
    (err, out) = rgwadmin(ctx, client, [
            'subuser', 'rm', '--subuser', subuser2,
            '--key-type', 'swift', '--purge-keys',
            ])
    assert not err
    assert len(out['swift_keys']) == 0
    assert len(out['subusers']) == 0

    # TESTCASE 'bucket-stats','bucket','stats','no session/buckets','succeeds, empty list'
    (err, out) = rgwadmin(ctx, client, ['bucket', 'stats', '--uid', user1])
    assert not err
    assert len(out) == 0

    # connect to rgw
    (remote,) = ctx.cluster.only(client).remotes.iterkeys()
    (remote_user, remote_host) = remote.name.split('@')
    connection = boto.s3.connection.S3Connection(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        is_secure=False,
        port=7280,
        host=remote_host,
        calling_format=boto.s3.connection.OrdinaryCallingFormat(),
        )

    # TESTCASE 'bucket-stats2','bucket','stats','no buckets','succeeds, empty list'
    (err, out) = rgwadmin(ctx, client, ['bucket', 'list', '--uid', user1])
    assert not err
    assert len(out) == 0

    # create a first bucket
    bucket = connection.create_bucket(bucket_name)

    # TESTCASE 'bucket-list','bucket','list','one bucket','succeeds, expected list'
    (err, out) = rgwadmin(ctx, client, ['bucket', 'list', '--uid', user1])
    assert not err
    assert len(out) == 1
    assert out[0] == bucket_name

    # TESTCASE 'max-bucket-limit,'bucket','create','4 buckets','5th bucket fails due to max buckets == 4'
    bucket2 = connection.create_bucket(bucket_name + '2')
    bucket3 = connection.create_bucket(bucket_name + '3')
    bucket4 = connection.create_bucket(bucket_name + '4')
    # the 5th should fail.
    failed = False
    try:
        connection.create_bucket(bucket_name + '5')
    except:
        failed = True
    assert failed

    # delete the buckets
    bucket2.delete()
    bucket3.delete()
    bucket4.delete()
   
    # TESTCASE 'bucket-stats3','bucket','stats','new empty bucket','succeeds, empty list'
    (err, out) = rgwadmin(ctx, client, [
            'bucket', 'stats', '--bucket', bucket_name])
    assert not err
    assert out['owner'] == user1
    bucket_id = out['id']

    # TESTCASE 'bucket-stats4','bucket','stats','new empty bucket','succeeds, expected bucket ID'
    (err, out) = rgwadmin(ctx, client, ['bucket', 'stats', '--uid', user1])
    assert not err
    assert len(out) == 1
    assert out[0]['id'] == bucket_id    # does it return the same ID twice in a row?

    # use some space
    key = boto.s3.key.Key(bucket)
    key.set_contents_from_string('one')

    # TESTCASE 'bucket-stats5','bucket','stats','after creating key','succeeds, lists one non-empty object'
    (err, out) = rgwadmin(ctx, client, [
            'bucket', 'stats', '--bucket', bucket_name])
    assert not err
    assert out['id'] == bucket_id
    assert out['usage']['rgw.main']['num_objects'] == 1
    assert out['usage']['rgw.main']['size_kb'] > 0

    # reclaim it
    key.delete()

    # TESTCASE 'bucket unlink', 'bucket', 'unlink', 'unlink bucket from user', 'fails', 'access denied error'
    (err, out) = rgwadmin(ctx, client, ['bucket', 'unlink', '--uid', user1, '--bucket', bucket_name])
    assert not err

    # create a second user to link the bucket to
    (err, out) = rgwadmin(ctx, client, [
            'user', 'create',
            '--uid', user2,
            '--display-name', display_name2,
            '--access-key', access_key2,
            '--secret', secret_key2,
            '--max-buckets', '1',
            ])
    assert not err

    # try creating an object with the first user before the bucket is relinked
    denied = False
    key = boto.s3.key.Key(bucket)

    try:
        key.set_contents_from_string('two')
    except boto.exception.S3ResponseError:
        denied = True

    assert not denied

    # delete the object
    key.delete()

    # link the bucket to another user
    (err, out) = rgwadmin(ctx, client, ['bucket', 'link', '--uid', user2, '--bucket', bucket_name])
    assert not err

    # try creating an object with the first user which should cause an error
    key = boto.s3.key.Key(bucket)

    try:
        key.set_contents_from_string('three')
    except boto.exception.S3ResponseError:
        denied = True

    assert denied

    # relink the bucket to the first user and delete the second user
    (err, out) = rgwadmin(ctx, client, ['bucket', 'link', '--uid', user1, '--bucket', bucket_name])
    assert not err

    (err, out) = rgwadmin(ctx, client, ['user', 'rm', '--uid', user2])
    assert not err

    # TESTCASE 'object-rm', 'object', 'rm', 'remove object', 'succeeds, object is removed'

    # upload an object
    object_name = 'four'
    key = boto.s3.key.Key(bucket, object_name)
    key.set_contents_from_string(object_name)

    # now delete it
    (err, out) = rgwadmin(ctx, client, ['object', 'rm', '--bucket', bucket_name, '--object', object_name])

    assert not err

    # TESTCASE 'bucket-stats6','bucket','stats','after deleting key','succeeds, lists one no objects'
    (err, out) = rgwadmin(ctx, client, [
            'bucket', 'stats', '--bucket', bucket_name])
    assert not err
    assert out['id'] == bucket_id
    assert out['usage']['rgw.main']['num_objects'] == 0

    # list log objects
    # TESTCASE 'log-list','log','list','after activity','succeeds, lists one no objects'
    (err, out) = rgwadmin(ctx, client, ['log', 'list'])
    assert not err
    assert len(out) > 0

    for obj in out:
        # TESTCASE 'log-show','log','show','after activity','returns expected info'
        (err, log) = rgwadmin(ctx, client, ['log', 'show', '--object', obj])
        assert not err
        assert len(log) > 0
        assert log['bucket'].find(bucket_name) == 0
        assert log['bucket'] != bucket_name or log['bucket_id'] == bucket_id 
        assert log['bucket_owner'] == user1 or log['bucket'] == bucket_name + '5'
        for entry in log['log_entries']:
            assert entry['bucket'] == log['bucket']
            assert entry['user'] == user1 or log['bucket'] == bucket_name + '5'

        # TESTCASE 'log-rm','log','rm','delete log objects','succeeds'
        (err, out) = rgwadmin(ctx, client, ['log', 'rm', '--object', obj])
        assert not err

    # TODO: show log by bucket+date

    # need to wait for all usage data to get flushed, should take up to 30 seconds
    timestamp = time.time()
    while time.time() - timestamp <= (20 * 60):      # wait up to 20 minutes
        (err, out) = rgwadmin(ctx, client, ['usage', 'show', '--categories', 'delete_obj'])  # last operation we did is delete obj, wait for it to flush
        if successful_ops(out) > 0:
            break;
        time.sleep(1)

    assert time.time() - timestamp <= (20 * 60)

    # TESTCASE 'usage-show' 'usage' 'show' 'all usage' 'succeeds'
    (err, out) = rgwadmin(ctx, client, ['usage', 'show'])
    assert not err
    assert len(out['entries']) > 0
    assert len(out['summary']) > 0
    user_summary = out['summary'][0]
    total = user_summary['total']
    assert total['successful_ops'] > 0

    # TESTCASE 'usage-show2' 'usage' 'show' 'user usage' 'succeeds'
    (err, out) = rgwadmin(ctx, client, ['usage', 'show', '--uid', user1])
    assert not err
    assert len(out['entries']) > 0
    assert len(out['summary']) > 0
    user_summary = out['summary'][0]
    for entry in user_summary['categories']:
        assert entry['successful_ops'] > 0
    assert user_summary['user'] == user1

    # TESTCASE 'usage-show3' 'usage' 'show' 'user usage categories' 'succeeds'
    test_categories = ['create_bucket', 'put_obj', 'delete_obj', 'delete_bucket']
    for cat in test_categories:
        (err, out) = rgwadmin(ctx, client, ['usage', 'show', '--uid', user1, '--categories', cat])
        assert not err
        assert len(out['summary']) > 0
        user_summary = out['summary'][0]
        assert user_summary['user'] == user1
        assert len(user_summary['categories']) == 1
        entry = user_summary['categories'][0]
        assert entry['category'] == cat
        assert entry['successful_ops'] > 0

    # TESTCASE 'usage-trim' 'usage' 'trim' 'user usage' 'succeeds, usage removed'
    (err, out) = rgwadmin(ctx, client, ['usage', 'trim', '--uid', user1])
    assert not err
    (err, out) = rgwadmin(ctx, client, ['usage', 'show', '--uid', user1])
    assert not err
    assert len(out['entries']) == 0
    assert len(out['summary']) == 0

    # TESTCASE 'user-suspend2','user','suspend','existing user','succeeds'
    (err, out) = rgwadmin(ctx, client, ['user', 'suspend', '--uid', user1])
    assert not err

    # TESTCASE 'user-suspend3','user','suspend','suspended user','cannot write objects'
    try:
        key = boto.s3.key.Key(bucket)
        key.set_contents_from_string('five')
    except boto.exception.S3ResponseError as e:
        assert e.status == 403

    # TESTCASE 'user-renable2','user','enable','suspended user','succeeds'
    (err, out) = rgwadmin(ctx, client, ['user', 'enable', '--uid', user1])
    assert not err

    # TESTCASE 'user-renable3','user','enable','reenabled user','can write objects'
    key = boto.s3.key.Key(bucket)
    key.set_contents_from_string('six')

    # TESTCASE 'gc-list', 'gc', 'list', 'get list of objects ready for garbage collection'

    # create an object large enough to be split into multiple parts
    test_string = 'foo'*10000000

    big_key = boto.s3.key.Key(bucket)
    big_key.set_contents_from_string(test_string)

    # now delete the head
    big_key.delete()

    # wait a bit to give the garbage collector time to cycle
    time.sleep(15)

    (err, out) = rgwadmin(ctx, client, ['gc', 'list'])

    assert len(out) > 0

    # TESTCASE 'gc-process', 'gc', 'process', 'manually collect garbage'
    (err, out) = rgwadmin(ctx, client, ['gc', 'process'])

    assert not err

    #confirm
    (err, out) = rgwadmin(ctx, client, ['gc', 'list'])

    assert len(out) == 0

    # TESTCASE 'rm-user-buckets','user','rm','existing user','fails, still has buckets'
    (err, out) = rgwadmin(ctx, client, ['user', 'rm', '--uid', user1])
    assert err

    # delete should fail because ``key`` still exists
    fails = False
    try:
        bucket.delete()
    except boto.exception.S3ResponseError as e:
        assert e.status == 409

    key.delete()
    bucket.delete()

    # TESTCASE 'policy', 'bucket', 'policy', 'get bucket policy', 'returns S3 policy'
    bucket = connection.create_bucket(bucket_name)

    # create an object
    key = boto.s3.key.Key(bucket)
    key.set_contents_from_string('seven')

    # should be private already but guarantee it
    key.set_acl('private')

    (err, out) = rgwadmin(ctx, client, ['policy', '--bucket', bucket.name, '--object', key.key])

    assert not err

    acl = key.get_xml_acl()

    assert acl == out.strip('\n')

    # add another grantee by making the object public read
    key.set_acl('public-read')

    (err, out) = rgwadmin(ctx, client, ['policy', '--bucket', bucket.name, '--object', key.key])

    assert not err

    acl = key.get_xml_acl()
    assert acl == out.strip('\n')

    # TESTCASE 'rm-bucket', 'bucket', 'rm', 'bucket with objects', 'succeeds'
    bucket = connection.create_bucket(bucket_name)
    key_name = ['eight', 'nine', 'ten', 'eleven']
    for i in range(4):
        key = boto.s3.key.Key(bucket)
        key.set_contents_from_string(key_name[i])

    (err, out) = rgwadmin(ctx, client, ['bucket', 'rm', '--bucket', bucket_name, '--purge-objects'])
    assert not err

    # TESTCASE 'caps-add', 'caps', 'add', 'add user cap', 'succeeds'
    caps='user=read'
    (err, out) = rgwadmin(ctx, client, ['caps', 'add', '--uid', user1, '--caps', caps])

    assert out['caps'][0]['perm'] == 'read'

    # TESTCASE 'caps-rm', 'caps', 'rm', 'remove existing cap from user', 'succeeds'
    (err, out) = rgwadmin(ctx, client, ['caps', 'rm', '--uid', user1, '--caps', caps])

    assert not out['caps']

    # TESTCASE 'rm-user','user','rm','existing user','fails, still has buckets'
    bucket = connection.create_bucket(bucket_name)
    key = boto.s3.key.Key(bucket)

    (err, out) = rgwadmin(ctx, client, ['user', 'rm', '--uid', user1])
    assert err

    # TESTCASE 'rm-user2', 'user', 'rm', user with data', 'succeeds'
    bucket = connection.create_bucket(bucket_name)
    key = boto.s3.key.Key(bucket)
    key.set_contents_from_string('twelve')

    (err, out) = rgwadmin(ctx, client, ['user', 'rm', '--uid', user1, '--purge-data' ])
    assert not err

    # TESTCASE 'rm-user3','user','rm','deleted user','fails'
    (err, out) = rgwadmin(ctx, client, ['user', 'info', '--uid', user1])
    assert err

    # TESTCASE 'pool-rm', 'pool', 'rm', 'make default pool unavailable', 'succeeds'
    default_pool='.rgw.buckets'
    (err, out) = rgwadmin(ctx, client, ['pool', 'rm', '--pool', default_pool])

    # now list the pools
    (err, out) = rgwadmin(ctx, client, ['pools', 'list'])

    assert len(out) == 0

    # TESTCASE 'pool-add', 'pool', 'add', 'make default pool available', 'succeeds'
    (err, out) = rgwadmin(ctx, client, ['pool', 'add', '--pool', default_pool])

    assert not err

    (err, out) = rgwadmin(ctx, client, ['pools', 'list'])
    assert out[0]['name'] == default_pool

    # TESTCASE 'zone-info', 'zone', 'info', 'get zone info', 'succeeds'
    (err, out) = rgwadmin(ctx, client, ['zone', 'info'])

    assert len(out) > 0
