import logging
import csv
import os

from teuthology.config import config
from teuthology.exceptions import ConfigError

log = logging.getLogger(__name__)


class CSVWriter:

    def __init__(self):
        self.field_names = ['Description', 'Scripts']
        self._contents = config.frag_ids
        self._path = os.path.normpath(config.frag_ids_path)

    def __rows(self):
        rows = []
        if self._contents:
            for each in self._contents:
                rows.append(dict(zip(self.field_names, each)))
            return rows

    def write(self):
        with open(self._path, 'w') as fp:
            writer = csv.DictWriter(fp, fieldnames=self.field_names)
            writer.writeheader()
            writer.writerows(self.__rows())

        log.info('csv file will be at {}'.format(self._path))


class Writer:
    def __init__(self,):
        supported = ['.csv']
        self._path = config.frag_ids_path
        self._filename, self._extension = os.path.splitext(self._path)
        if self._extension not in supported:
            raise ConfigError('unsupported file type, supported options are: {}'.format(','.join(supported)))

    def write(self):
        if self._extension == '.csv':
            csv_writer = CSVWriter()
            csv_writer.write()


