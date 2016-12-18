# -*- coding: utf-8 -*-

import csv
import sys
import json
import pprint
import logging
from GoogleScraper.database import Link, SERP
from pymongo import MongoClient
from datetime import datetime

"""Stores SERP results in the appropriate output format.

Streamline process, one serp object at the time, because GoogleScraper works incrementally.
Furthermore we cannot accumulate all results and then process them, because it would be
impossible to launch lang scrape jobs with millions of keywords.
"""

connection = MongoClient("mongodb://192.168.0.21")
db = connection.serank
c_serp = db.serp
c_action = db.action


output_format = 'stdout'
outfile = sys.stdout
csv_fieldnames = sorted(set(Link.__table__.columns._data.keys() + SERP.__table__.columns._data.keys()) - {'id', 'serp_id'})

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return json.JSONEncoder.default(self, o)


class JsonStreamWriter():
    """Writes consecutive objects to an json output file."""

    def __init__(self, filename):
        self.file = open(filename, 'wt')
        self.file.write('[')
        self.last_object = None

    def write(self, obj):
        if self.last_object:
            self.file.write(',')
        json.dump(obj, self.file, indent=2, sort_keys=True)
        self.last_object = id(obj)

    def end(self):
        self.file.write(']')
        self.file.close()


class CsvStreamWriter():
    """
    Writes consecutive objects to an csv output file.
    """
    def __init__(self, filename):
        # every row in the csv output file should contain all fields
        # that are in the table definition. Except the id, they have the
        # same name in both tables
        self.file = open(filename, 'wt')
        self.dict_writer = csv.DictWriter(self.file, fieldnames=csv_fieldnames, delimiter=',')
        self.dict_writer.writeheader()

    def write(self, data, serp):
        # one row per link
        for row in data['results']:
            d = row2dict(serp)
            d.update(row)
            d = ({k: v if type(v) is str else v for k, v in d.items() if k in csv_fieldnames})
            self.dict_writer.writerow(d)

    def end(self):
        self.file.close()


def init_outfile(config, force_reload=False):
    global outfile, output_format

    if not outfile or force_reload:

        output_file = config.get('output_filename', '')

        if output_file.endswith('.json'):
            output_format = 'json'
        elif output_file.endswith('.csv'):
            output_format = 'csv'

        # the output files. Either CSV or JSON or STDOUT
        # It's little bit tricky to write the JSON output file, since we need to
        # create the array of the most outer results ourselves because we write
        # results as soon as we get them (it's impossible to hold the whole search in memory).
        if output_format == 'json':
            outfile = JsonStreamWriter(output_file)
        elif output_format == 'csv':
            outfile = CsvStreamWriter(output_file)
        elif output_format == 'stdout':
            outfile = sys.stdout


def store_serp_result(serp, config):
    """Store the parsed SERP page.

    Stores the results from scraping in the appropriate output format.

    Either stdout, json or csv output format.

    This function may be called from a SearchEngineScrape or from
    caching functionality. When called from SearchEngineScrape, then
    a parser object is passed.
    When called from caching, a list of serp object are given.

    Args:
        serp: A serp object
    """
    global outfile, output_format

    if outfile:
        data = row2dict(serp)
        data['date'] = datetime.utcnow()
        try:
            action_id = c_action.insert(data)
        except Exception as e:
            action_id = False
            print("Failed:", e)
        # data['results'] = []
        if action_id:
            for link in serp.links:
                # data['results'].append(row2dict(link))
                serp = row2dict(link)
                serp['date'] = datetime.utcnow()
                serp['query'] = data['query']
                serp['search_engine_name'] = data['search_engine_name']
                serp['requested_at'] = data['requested_at']
                serp['action'] = action_id
                c_serp.insert(serp)
        if output_format == 'json':
            # The problem here is, that we need to stream write the json data.
            # outfile.write(data)
            pass
        elif output_format == 'csv':
            outfile.write(data, serp)
        elif output_format == 'stdout':
            if config.get('print_results') == 'summarize':
                print(serp)
            elif config.get('print_results') == 'all':
                pprint.pprint(data)


def row2dict(obj):
    """Convert sql alchemy object to dictionary."""
    d = {}
    for column in obj.__table__.columns:
        d[column.name] = str(getattr(obj, column.name))

    return d


def close_outfile():
    """
    Closes the outfile.
    """
    global outfile
    if output_format in ('json', 'csv'):
        outfile.end()
