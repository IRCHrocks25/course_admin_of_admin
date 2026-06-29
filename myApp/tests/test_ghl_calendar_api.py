from unittest import mock

from django.test import SimpleTestCase

from myApp.integrations.ghl import calendar_api


class CalendarApiTests(SimpleTestCase):
    @mock.patch("myApp.integrations.ghl.calendar_api.requests.get")
    def test_get_calendars_returns_normalized_calendar_rows(self, mock_get):
        mock_get.return_value.json.return_value = {
            "calendars": [
                {
                    "id": "CALW",
                    "name": "Webinar",
                    "calendarType": "class_booking",
                    "description": "Live event calendar",
                }
            ]
        }

        rows = calendar_api.get_calendars("tok", "LOC1")

        self.assertEqual(rows, [
            {
                "id": "CALW",
                "name": "Webinar",
                "calendarType": "class_booking",
                "description": "Live event calendar",
            }
        ])
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"], {"locationId": "LOC1"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")
