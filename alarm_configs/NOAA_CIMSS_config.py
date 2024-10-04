alarm_type = "NOAA_CIMSS"
alarm_name = "NOAA CIMSS"

volc_file = "alarm_aux_files/volcano_list.xlsx"
outfile = "alarm_aux_files/NOAA_CIMSS_last.txt"
img_file = "alarm_aux_files/noaa_out_.png"


max_distance = 25  # maximum distance for sending an alert
mattermost_channel_id = "jcusdzgyhfb4jq65af3zw6pcwa"


# send alerts from elevated volcanoes to dedicated MM channel
elevated_volcano_dist = 20  # distance threshold in kms
elevated_volcano_list = ["Great Sitkin"]
elevated_volcano_mm = "tskignhcuf88fcxsmuqzn4jtfh"


# send thermal alerts to dedicated MM channel
thermal_alert_dist = 20  # distance threshold in kms
thermal_alerts_mm = "yqz7dynxo7dedg6nx9py1uhdfy"
