import json
from datetime import datetime, timedelta

import requests
from dateutil import rrule

# start date is american 06-30-2020
# number of nights defines the range to look in
# consecutive_nights_required is the min number of nights we want consecutive
# we can add smth like max_switches later


def get_proxies():
    resp = requests.get(
        url='http://pubproxy.com/api/proxy?last_check=60&country=US,CA',
        data=json.dumps({
            'last_check': 30,
            'country': 'US,CA',
            'type': 'http',
            'https': True,
            'post': True
        })
    )

    """
    sample response
        {
        "data":[
            {
                "ipPort":"123.12.12.123:80",
                "ip":"123.12.12.123",
                "port":"80",
                "country":"US",
                "last_checked":"2023-08-22 10:29:33",
                "proxy_level":"elite",
                "type":"http",
                "speed":"2.2",
                "support":{
                    "https":1,
                    "get":1,
                    "post":1,
                    "cookies":1,
                    "referer":1,
                    "user_agent":1,
                    "google":1
                }
            }
        ],
        "count":1
        }
    """
    return {
        'http': resp.json()['data'][0]['ipPort'],
        'https': resp.json()['data'][0]['ipPort']
    }


def check_reserve_california(facility_id, start_date, number_of_nights, consecutive_nights_required):
    response = requests.post(
        url='https://calirdr.usedirect.com/rdr/rdr/search/grid',
        proxies=get_proxies(),
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

    print(
        f'[Reserve California] facility {facility_id} {start_date} days={days_available} max_consecutive={max_consecutive}')

    return max_consecutive >= consecutive_nights_required


def check_recreation_gov_campsites(facility_id, start_date, number_of_nights, consecutive_nights_required):
    start_date = datetime.strptime(start_date, '%m-%d-%Y')
    end_date = start_date + timedelta(number_of_nights - 1)
    start_of_month = datetime(start_date.year, start_date.month, 1)
    months = list(rrule.rrule(
        rrule.MONTHLY, dtstart=start_of_month, until=end_date))

    dates_of_interest = []
    for delta in range(number_of_nights):
        new_date = start_date + timedelta(delta)
        dates_of_interest.append(format_recreation_gov_date(new_date))

    # Get data for each month.
    api_data = []
    for month_date in months:
        response = requests.get(
            url='https://www.recreation.gov/api/camps/availability/campground/{}/month'.format(
                facility_id),
            proxies=get_proxies(),
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

    print(
        f'[recreation.gov] facility {facility_id} {start_date} days={availability_array} max_consecutive={max_consecutive}')

    return max_consecutive >= consecutive_nights_required


def check_recreation_gov_permit(permit_id, site_ids, number_of_people, start_date, number_of_nights, consecutive_nights_required):
    start_date = datetime.strptime(start_date, '%m-%d-%Y')
    end_date = start_date + timedelta(number_of_nights - 1)
    start_of_month = datetime(start_date.year, start_date.month, 1)
    months = list(rrule.rrule(
        rrule.MONTHLY, dtstart=start_of_month, until=end_date))

    dates_of_interest = []
    for delta in range(number_of_nights):
        new_date = start_date + timedelta(delta)
        dates_of_interest.append(format_recreation_gov_date(new_date))

    # Get data for each month.
    api_data = []
    for month_date in months:
        response = requests.get(
            url='https://www.recreation.gov/api/permits/{}/availability/month'.format(
                permit_id),
            proxies=get_proxies(),
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

    print(
        f'[recreation.gov] permit {permit_id} {start_date} number_of_people={number_of_people} days={availability_array} max_consecutive={max_consecutive}')

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
