# Mailman3 LDAP Sync

Synchronizing mailman3 list against ldap with ease. has been tested for OpenLDAP and Active Directory.

Features:
- Supporting Python 2.7 above (including 3.X)
- Search through DN if group member is a DN record (Active Directory)
- Adding some prefix in list name
- Hooks, module that will be executed in the end of script
- Excluding list for being deleted by regex pattern


## Installing

- Clone repository
```sh
git clone https://github.com/iomarmochtar/mailman3_ldap_sync
```

- Go to cloned directory
```
cd mailman3_ldap_sync
```

- **[optional]** Create virtual environment
```
virtualenv virtenv
source virtenv/bin/activate
```

- Install all requirements using pip command
```
pip install -r requirements.txt
```

- Set script as executeable
```
chmod +x m3_sync.py
```

- Make a copy of main configuration file
```
cp config.ini_dist config.ini
```

- Adjust configuration file as your needs, you can also see config documentation inside
```
vi config.ini
```

## Logrotate

If you are enabling script log file and run script scheduled (using crontab) then you may set log rotation for not make it's bigger time by time.

**/etc/logrotate.d/mailman3_ldapsync**
```
/var/log/mailman3_ldapsync.log {
    daily
    missingok
    notifempty
    create 0644 root root
    compress
}
```

## Using the Script

Run like a boss
```sh
./m3_sync.py
```
