import ast
import os
import smtplib
import ssl
from datetime import datetime

import requests
import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from fetch_data import (check_recreation_gov_campsites,
                        check_recreation_gov_permit, check_reserve_california)


def campsite_schedule_cron(source, site_name, facility_id, start_date, number_of_nights, consecutive_nights_required):
    if datetime.strptime(start_date, "%m-%d-%Y") < datetime.today():
        print(source, site_name, facility_id, start_date, number_of_nights,
              consecutive_nights_required, 'skipped')
        return
    print(f'checking {source} for {site_name} campsites starting {start_date}')
    if source == 'reserve_california':
        result = check_reserve_california(facility_id, start_date, number_of_nights, consecutive_nights_required)
    elif source == 'recreation_gov' or source == 'reserve_america':
        result = check_recreation_gov_campsites(facility_id, start_date, number_of_nights, consecutive_nights_required)
    else:
        raise ValueError(f'source {source} not supported.')

    print(f'checking {source} for {site_name} campsites starting {start_date} result {result}')
    if result:
        notify_users(source, site_name, start_date, number_of_nights, consecutive_nights_required, facility_id=facility_id)


def permit_schedule_cron(site_name, permit_id, sites, number_of_nights, number_of_permits, start_date, consecutive_nights_required):
    if datetime.strptime(start_date, "%m-%d-%Y") < datetime.today():
        print(site_name, permit_id, sites, number_of_nights, number_of_permits,
              start_date, consecutive_nights_required, 'skipped')
        return
    print(f'checking {source} for {site_name} permits starting {start_date}')
    site_ids = [str(entry['id']) for entry in sites]

    result = check_recreation_gov_permit(permit_id, site_ids, number_of_permits,
                                          start_date, number_of_nights, consecutive_nights_required)

    if result:
        notify_users(source, permit_id, site_name, start_date, number_of_nights,
                     consecutive_nights_required, number_of_permits=number_of_permits)


notified_sites = {}

sender_email = os.environ['SENDER_EMAIL']
receiver_emails = ast.literal_eval(os.environ['RECEIVER_EMAILS'])
receiver_sms = ast.literal_eval(os.environ['RECEIVER_SMS'])
context = ssl.create_default_context()
port = 465


def send_email(message):
    print(f'messaging users {message}')

    with smtplib.SMTP_SSL("in-v3.mailjet.com", port, context=context) as server:
        server.login(os.environ['MAILJET_API_KEY'], os.environ['MAILJET_PASSWORD'])
        for receiver in receiver_emails:
            server.sendmail(sender_email, receiver, message)


def send_sms(message):
    if os.environ.get('BLOWERIO_URL'):
        # blowerio is set
        for user in receiver_sms:
            resp = requests.post(os.environ['BLOWERIO_URL'] + '/messages', data={'to': user, 'message': message})
            print(resp.json())


def notify_users(source, site_name, start_date, number_of_nights, consecutive_nights_required, number_of_permits=None, facility_id=None):
    key = (site_name, start_date, number_of_nights, consecutive_nights_required, number_of_permits)
    if notified_sites.get(key, 0) >= 1:
        print(f'already notified, skipping')
        return

    message = f'found availability on {source} for {site_name} starting {start_date} for {consecutive_nights_required} night(s).'

    if facility_id is not None and (source == 'recreation_gov' or source == 'reserve_america'):
        message += f' Book campsite at https://www.recreation.gov/camping/campgrounds/{facility_id}.'

    # send_email(message)
    send_sms(message)

    if (site_name, start_date, number_of_nights, consecutive_nights_required, number_of_permits) in notified_sites:
        notified_sites[key] += 1
    else:
        notified_sites[key] = 1


def clear_notified():
    global notified_sites
    notified_sites = {}

MINUTES_INTERVAL = 3  # minute(s)
SECONDS_INTERVAL = 10

if __name__ == '__main__':

    with open('./config.yaml', 'r') as file:
        data = yaml.full_load(file)

    if data:
        print('Starting scheduler')
        scheduler = BlockingScheduler()

        for source, entries in data.get('campsites', {}).items():
            for entry in entries:
                site_name = entry['name']
                facility_id = entry['facility_id']
                start_date = entry['start_date']
                number_of_nights = entry['number_of_nights']
                consecutive_nights_required = entry['consecutive_nights_required']

                print(f'setting up campsites-{source}-{site_name} {start_date} to run every {MINUTES_INTERVAL} minute(s)')

                scheduler.add_job(campsite_schedule_cron, args=[source, site_name, facility_id, start_date, number_of_nights, consecutive_nights_required],
                                  trigger='interval',
                                  minutes=MINUTES_INTERVAL,
                                  jitter=60,
                                  # seconds=SECONDS_INTERVAL,
                                  coalesce=True)

        for source, entries in data.get('permits', {}).items():
            for entry in entries:
                site_name = entry['name']
                permit_id = str(entry['permit_id'])
                start_date = entry['start_date']
                number_of_nights = entry['number_of_nights']
                number_of_permits = entry['number_of_permits']
                sites = entry['sites']
                consecutive_nights_required = entry['consecutive_nights_required']

                print(f'setting up permits-{source}-{site_name} {start_date} to run every {MINUTES_INTERVAL} minute(s)')

                scheduler.add_job(permit_schedule_cron, args=[site_name, permit_id, sites, number_of_nights, number_of_permits, start_date, consecutive_nights_required],
                                  trigger='interval',
                                  minutes=MINUTES_INTERVAL,
                                  jitter=60,
                                  # seconds=SECONDS_INTERVAL,
                                  coalesce=True)

        print(f'Setting up notified_sites to clear every 4 hours')
        scheduler.add_job(clear_notified, trigger='interval', hours=4, max_instances=1, coalesce=True)
        try:
            scheduler.start()
        except Exception as e:
            print(e)
