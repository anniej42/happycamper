import sys

import modal

stub = modal.Stub("example-hello-world")
stub.notified_sites = modal.Dict.new()

import ast
import os
import smtplib
import ssl

import requests
import yaml
import json
from datetime import datetime, timedelta
from dateutil import rrule

# start date is american 06-30-2020
# number of nights defines the range to look in
# consecutive_nights_required is the min number of nights we want consecutive
# we can add smth like max_switches later

# proxies = {
#     'http': 'http://localhost:8080',
#     'https': 'http://localhost:8080'
# }

def check_reserve_california(facility_id, start_date, number_of_nights, consecutive_nights_required):
    response = requests.post(
        url='https://calirdr.usedirect.com/rdr/rdr/search/grid',
        # roxies=proxies,
        headers={
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/json',
            'X-Remote-IP': '127.0.0.1',
            'X-Originating-IP': '127.0.0.1',
            'X-Forwarded-For': '127.0.0.1',
            'X-Remote-Addr': '127.0.0.1'
        },
        data=json.dumps({
            'StartDate': start_date,
            'FacilityId': str(facility_id),
            'SleepingUnitId': 0,
            'UnitTypeId': 0,
            'UnitCategoryId': 0,
        })
    )
    units = response.json()['Facility']['Units']
    days_available = [False] * number_of_nights
    for _, unit in units.items():
        if unit['IsAda']:
            continue
        for index, date in enumerate(sorted(list(unit['Slices'].keys()))[:number_of_nights]):
            days_available[index] = days_available[index] or unit['Slices'][date]['IsFree']

    max_consecutive = evaluate_boolean_array(days_available)

    print(f'[Reserve California] facility {facility_id} {start_date} days={days_available} max_consecutive={max_consecutive}')

    return max_consecutive >= consecutive_nights_required

def check_recreation_gov_campsites(facility_id, start_date, number_of_nights, consecutive_nights_required):
    start_date = datetime.strptime(start_date, '%m-%d-%Y')
    end_date = start_date + timedelta(number_of_nights - 1)
    start_of_month = datetime(start_date.year, start_date.month, 1)
    months = list(rrule.rrule(rrule.MONTHLY, dtstart=start_of_month, until=end_date))

    dates_of_interest = []
    for delta in range(number_of_nights):
        new_date = start_date + timedelta(delta)
        dates_of_interest.append(format_recreation_gov_date(new_date))

    # Get data for each month.
    api_data = []
    for month_date in months:
        response = requests.get(
            url='https://www.recreation.gov/api/camps/availability/campground/{}/month'.format(facility_id),
            # proxies=proxies,
            params={
                'start_date': format_recreation_gov_date_as_input(month_date),
            },
            headers={
                'Authority': 'www.recreation.gov',
                'Pragma': 'no-cache',
                'Accept': 'application/json, text/plain, */*',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36',
            },
        )
        api_data.append(response.json())

    availability_array = []
    for month_data in api_data:
        site_ids = list(month_data.get('campsites', {}).keys())
        for date_key in dates_of_interest:
            available_bool = any([month_data['campsites'][site_id]['availabilities'].get(date_key) == 'Available'
                                  for site_id in site_ids
                                  if month_data['campsites'][site_id]['capacity_rating'] == 'Single' and month_data['campsites'][site_id]['campsite_type'] != 'EQUESTRIAN NONELECTRIC'])
            availability_array.append(available_bool)

    max_consecutive = evaluate_boolean_array(availability_array)

    print(f'[recreation.gov] facility {facility_id} {start_date} days={availability_array} max_consecutive={max_consecutive}')

    return max_consecutive >= consecutive_nights_required

def check_recreation_gov_permit(permit_id, site_ids, number_of_people, start_date, number_of_nights, consecutive_nights_required):
    start_date = datetime.strptime(start_date, '%m-%d-%Y')
    end_date = start_date + timedelta(number_of_nights - 1)
    start_of_month = datetime(start_date.year, start_date.month, 1)
    months = list(rrule.rrule(rrule.MONTHLY, dtstart=start_of_month, until=end_date))

    dates_of_interest = []
    for delta in range(number_of_nights):
        new_date = start_date + timedelta(delta)
        dates_of_interest.append(format_recreation_gov_date(new_date))

    # Get data for each month.
    api_data = []
    for month_date in months:
        response = requests.get(
            url='https://www.recreation.gov/api/permits/{}/availability/month'.format(permit_id),
            # proxies=proxies,
            params={
                'start_date': format_recreation_gov_date_as_input(month_date),
            },
            headers={
                'Authority': 'www.recreation.gov',
                'Pragma': 'no-cache',
                'Accept': 'application/json, text/plain, */*',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36',
            },
        )
        api_data.append(response.json())

    availability_array = []
    for month_data in api_data:
        sites_data = month_data['payload']['availability']
        for date_key in dates_of_interest:
            available_bool = any([sites_data[site_id]['date_availability'].get(date_key, {}).get('remaining', 0) >= number_of_people
                                  for site_id in site_ids])
            availability_array.append(available_bool)

    max_consecutive = evaluate_boolean_array(availability_array)

    print(f'[recreation.gov] permit {permit_id} {start_date} number_of_people={number_of_people} days={availability_array} max_consecutive={max_consecutive}')

    return max_consecutive >= consecutive_nights_required

def format_recreation_gov_date_as_input(date_obj):
    return f'{date_obj.strftime("%Y-%m-%d")}T00:00:00.000Z'

def format_recreation_gov_date(date_obj):
    return f'{date_obj.strftime("%Y-%m-%d")}T00:00:00Z'

def evaluate_boolean_array(availabilities):
    max_consecutive = 0
    current_consecutive = 0
    for day_available in availabilities:
        if day_available:
            current_consecutive += 1
        else:
            max_consecutive = max(max_consecutive, current_consecutive)
            current_consecutive = 0
    return max(max_consecutive, current_consecutive)

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
    print(f'checking {source} for {site_name} permits starting {start_date}')
    site_ids = [str(entry['id']) for entry in sites]

    result = check_recreation_gov_permit(permit_id, site_ids, number_of_permits,
                                          start_date, number_of_nights, consecutive_nights_required)
    
    if result:
        notify_users(source, site_name, start_date, number_of_nights,
                     consecutive_nights_required, number_of_permits=number_of_permits)


def send_email(message):
    print(f'messaging users {message}')
    receiver_emails = ast.literal_eval(os.environ['NOTIFY_EMAILS'])
    with smtplib.SMTP_SSL("smtp.sendgrid.net", 465, context=ssl.create_default_context()) as server:
        server.login(os.environ['SENDGRID_USERNAME'], os.environ['SENDGRID_PASSWORD'])
        for receiver in receiver_emails:
            server.sendmail(os.environ['SENDER_EMAIL'], receiver, message)

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


my_image = modal.Image.debian_slim().pip_install("python-dateutil", "requests", "PyYAML")

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