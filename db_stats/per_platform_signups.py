import sys
import json

import time
import datetime

from os.path import expanduser
from collections import defaultdict

import yaml
from psycopg2 import connect
from tqdm import tqdm

import MySQLdb

class Config:

    def __init__(self):
        with open(expanduser('~') + '/.stats', 'r') as config_file:
            config = yaml.safe_load(config_file)
            self.DB_NAME = config['db_name']
            self.DB_USER = config['db_user']
            self.DB_PASSWORD = config['db_password']
            self.DB_HOST = config['db_host']
            self.MYSQL_PASSWORD = config['mysql_password']

CONFIG = Config()


connection = connect(dbname=CONFIG.DB_NAME,
                     user=CONFIG.DB_USER,
                     password=CONFIG.DB_PASSWORD,
                     host=CONFIG.DB_HOST,
                     options='-c search_path=matrix')

def ua_to_platform(ua):
    if not ua:
        return None
    ua = ua.lower()
    if 'iphone' in ua:
        return 'IOS'
    elif 'android' in ua:
        return 'ANDROID'
    else:
        return 'WEB/ELECTRON'

def str_to_ts(datestring):
    return int(time.mktime(datetime.datetime.strptime(datestring, "%Y-%m-%d").timetuple()))

def epoch_to_midnight_utc(epoch):
    d = datetime.datetime.fromtimestamp(epoch)
    return int(d.replace(hour=0, minute=0, second=0).timestamp())

class Entities:

    @staticmethod
    def get_users(connection, start, end):
        query = """
        SELECT name, creation_ts
        FROM users
        WHERE creation_ts >= %(start)s
        AND creation_ts < %(end)s
        AND password_hash != ''
        """
        with connection.cursor() as cursor:
            cursor.execute(query, {
                'start': str_to_ts(start),
                'end': str_to_ts(end)
            })
            return [{'user_id': row[0], 'timestamp': epoch_to_midnight_utc(row[1]) * 1000}
                    for row in cursor] 
    
    @staticmethod
    def get_creation_device(connection, user):
        query = """
        SELECT user_agent
        FROM user_daily_visits udv
        JOIN user_ips uip
        ON udv.user_id = uip.user_id
        AND udv.device_id = uip.device_id
        WHERE udv.user_id = %(user_id)s
        AND udv.timestamp = %(timestamp)s
        AND uip.ip != '-'
        ORDER BY uip.last_seen ASC
        LIMIT 1
        """
        with connection.cursor() as cursor:
            cursor.execute(query, user)
            results = [row[0] for row in cursor]
            if len(results) == 0:
                return None
            else:
                return results[0]

if len(sys.argv) == 3:
    FORMAT = '%Y-%m-%d'
    start = datetime.datetime.strptime(sys.argv[1], FORMAT)
    end = datetime.datetime.strptime(sys.argv[2], FORMAT)
else:
    end = datetime.datetime.today()
    start = end - datetime.timedelta(days=1)

#Populate the dict
stats = {}
for d in range((end - start).days):
    stats[str((start + datetime.timedelta(days=d)).date())] = {'ANDROID': 0, 'IOS': 0, 'WEB/ELECTRON': 0, None: 0}

users = Entities.get_users(connection, str(start.date()), str(end.date()))
for user in tqdm(users):
    platform = ua_to_platform(Entities.get_creation_device(connection, user))
    d = str(datetime.datetime.fromtimestamp(user['timestamp'] / 1000).date())
    stats[d][platform] += 1

class Helper:
    """Misc helper methods"""

    @staticmethod 
    def create_table(db, schema):
        """This method executes a CREATE TABLE IF NOT EXISTS command
        _without_ generating a mysql warning if the table already exists."""
        cursor = db.cursor()  
        cursor.execute('SET sql_notes = 0;')
        cursor.execute(schema)
        cursor.execute('SET sql_notes = 1;')
        db.commit()

TABLE_NAME = 'riot_signups_by_platform'
SCHEMA = """
CREATE TABLE IF NOT EXISTS
%s (
    date DATE NOT NULL,
    platform VARCHAR(12) NOT NULL,
    total INT
);
""" % TABLE_NAME

# Connect to and setup db:
db = MySQLdb.connect(host='localhost',
                     user='businessmetrics',
                     passwd=CONFIG.MYSQL_PASSWORD,
                     db='businessmetrics',
                     port=3306)
Helper.create_table(db, SCHEMA)

with db.cursor() as cursor:
    format_strings = ','.join(['%s'] * len(stats.keys()))
    delete_entries = """
    DELETE FROM riot_signups_by_platform
    WHERE date in (%s)
    """ % format_strings
    cursor.execute(delete_entries, stats.keys())
    db.commit()
    
    insert_entries = """
    INSERT INTO riot_signups_by_platform
    VALUES (%s, %s, %s)
    """
    for date, values in stats.items():
        print(values)
        for platform, count in values.items():
            if not platform:
                platform = 'None'
            print(date, platform, count) 
            cursor.execute(insert_entries, (date, platform, count))
    db.commit()

