import modal

stub = modal.Stub("example-hello-world")
stub.notified_sites = modal.Dict.new()

import ast
import os
import smtplib
import ssl
from datetime import datetime

import requests
import yaml
from dateutil import rrule

from fetch_data import (check_recreation_gov_campsites,
                        check_recreation_gov_permit, check_reserve_california)

# start date is american 06-30-2020
# number of nights defines the range to look in
# consecutive_nights_required is the min number of nights we want consecutive
# we can add smth like max_switches later


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
        notify_users(source, site_name, start_date, number_of_nights, consecutive_nights_required)

def permit_schedule_cron(site_name, permit_id, sites, number_of_nights, number_of_permits, start_date, consecutive_nights_required):
    if datetime.strptime(start_date, "%m-%d-%Y") < datetime.today():
        print(site_name, permit_id, sites, number_of_nights, number_of_permits,
              start_date, consecutive_nights_required, 'skipped')
        return
    print(f'checking recreation.gov for {site_name} permits starting {start_date}')
    site_ids = [str(entry['id']) for entry in sites]

    result = check_recreation_gov_permit(permit_id, site_ids, number_of_permits,
                                          start_date, number_of_nights, consecutive_nights_required)
    
    if result:
        notify_users('recreation.gov', site_name, start_date, number_of_nights,
                     consecutive_nights_required, number_of_permits=number_of_permits)


def send_email(message):
    print(f'messaging users {message}')
    receiver_emails = ast.literal_eval(os.environ['NOTIFY_EMAILS'])
    sender = os.environ['SENDER_EMAIL']
    with smtplib.SMTP_SSL("smtp.sendgrid.net", 465, context=ssl.create_default_context()) as server:
        server.login(os.environ['SENDGRID_USERNAME'], os.environ['SENDGRID_PASSWORD'])
        for receiver in receiver_emails:
            text = f'From: {sender}\nTo: {receiver}\nSubject: availability\n\n{message}'
            server.sendmail(sender, receiver, text)

def notify_users(source, site_name, start_date, number_of_nights, consecutive_nights_required, number_of_permits=None):
    key = (site_name, start_date, number_of_nights, consecutive_nights_required, number_of_permits)
    if stub.notified_sites.contains(key) and  stub.notified_sites.get(key)>= 3:
        print(f'already notified, skipping')
        return

    message = f'found availability on {source} for {site_name} starting {start_date} for {consecutive_nights_required} night(s).'
    send_email(message)

    if (site_name, start_date, number_of_nights, consecutive_nights_required, number_of_permits) in stub.notified_sites:
        stub.notified_sites[key] += 1
    else:
        stub.notified_sites[key] = 1

def clear_notified():
    stub.notified_sites = {}


my_image = modal.Image.debian_slim().pip_install("python-dateutil", "requests", "PyYAML", "free-proxy")

def get_data():
    return yaml.full_load(os.environ["CAMPSITES"])

@stub.function(image=my_image, secrets=[modal.Secret.from_name("campsites"), modal.Secret.from_name("sendgrid")])
def check_availability():
    data = get_data()

    if data:
        for source, entries in data.get('campsites', {}).items():
            for entry in entries:
                site_name = entry['name']
                facility_id = entry['facility_id']
                start_date = entry['start_date']
                number_of_nights = entry['number_of_nights']
                consecutive_nights_required = entry['consecutive_nights_required']

                print(f'setting up campsites-{source}-{site_name} {start_date} to run every')

                campsite_schedule_cron(source, site_name, facility_id, start_date, number_of_nights, consecutive_nights_required)
                                    
        for source, entries in data.get('permits', {}).items():
            for entry in entries:
                site_name = entry['name']
                permit_id = str(entry['permit_id'])
                start_date = entry['start_date']
                number_of_nights = entry['number_of_nights']
                number_of_permits = entry['number_of_permits']
                sites = entry['sites']
                consecutive_nights_required = entry['consecutive_nights_required']

                print(f'setting up permits-{source}-{site_name} {start_date} to run ')

                permit_schedule_cron(site_name, permit_id, sites, number_of_nights, number_of_permits, start_date, consecutive_nights_required)

@stub.local_entrypoint()
def main():
    check_availability.remote()