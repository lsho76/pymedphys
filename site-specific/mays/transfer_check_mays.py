# Copyright (C) 2020 Jacob Rembish

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import streamlit as st

from pymedphys._mosaiq import connect

from pymedphys._experimental.chartchecks.compare import color_results, compare_to_mosaiq
from pymedphys._experimental.chartchecks.helpers import (
    get_all_dicom_treatment_info,
    get_all_treatment_data,
    get_staff_initials,
)
from pymedphys._experimental.chartchecks.tolerance_constants import (
    SITE_CONSTANTS,
    TOLERANCE_TYPES,
)

from pymedphys._experimental.chartchecks.dvh_helpers import plot_dvh


# currdir = os.getcwd()
server = "PRDMOSAIQIWVV01.utmsa.local"

st.title("Data Transfer Check")
st.sidebar.header("Instructions:")
st.sidebar.markdown(
    """
To use this application, you must have the RP file of the plan you want to check. This can be exported in Pinnacle.
You will get an error if you select a QA RP file.

When exporting the DICOM, only the RP is needed. Once you have that, you can select it where prompted and the application
will run.
"""
)
dicomFiles = st.file_uploader(
    "Please select a RP file.", force=True, accept_multiple_files=True
)

files = {}
for dicomFile in dicomFiles:
    name = dicomFile.name
    if "RP" in name:
        files["rp"] = dicomFile
    elif "RD" in name:
        files["rd"] = dicomFile
    elif "RS" in name:
        files["rs"] = dicomFile
    elif "CT" in name:
        files["ct"] = dicomFile
    else:
        continue


if "rp" in files:
    # retrieve data from both systems.
    dicom_table = get_all_dicom_treatment_info(files["rp"])
    dicom_table["tolerance"] = [
        TOLERANCE_TYPES[item] for item in dicom_table["tolerance"]
    ]
    dicom_table = dicom_table.sort_values(["field_label"])

    mrn = dicom_table.iloc[0]["mrn"]
    with connect.connect(server) as cursor:
        mosaiq_table = get_all_treatment_data(cursor, mrn)
        if mosaiq_table.iloc[0]["create_id"] is not None:
            try:
                site_initials = get_staff_initials(
                    cursor, str(int(mosaiq_table.iloc[0]["create_id"]))
                )
            except (TypeError, ValueError, AttributeError):
                site_initials = ""

    # mosaiq_table = mosaiq_table[mosaiq_table["field_version"] == 0]
    mosaiq_table = mosaiq_table[
        (mosaiq_table["site_version"] == 0)
        & (mosaiq_table["site_setup_version"] == 0)
        & (mosaiq_table["field_version"] == 0)
    ]
    mosaiq_table = mosaiq_table.reset_index(drop=True)
    mosaiq_table["tolerance"] = [
        TOLERANCE_TYPES[item] for item in mosaiq_table["tolerance"]
    ]
    ########################################################################################################################
    # verify general patient information between the two systems
    name = dicom_table.iloc[0]["first_name"] + " " + dicom_table.iloc[0]["last_name"]
    st.subheader("Patient:")

    if (
        name
        == mosaiq_table.iloc[0]["first_name"] + " " + mosaiq_table.iloc[0]["last_name"]
    ):
        st.success("Name: " + name)
    else:
        st.error("Name: " + name)

    if mrn == mosaiq_table.iloc[0]["mrn"]:
        st.success("MRN: " + mrn)
    else:
        st.error("MRN: " + mrn)

    DOB = str(mosaiq_table.iloc[0]["dob"])[0:10]
    dicom_DOB = dicom_table.iloc[0]["dob"]
    if DOB == dicom_DOB[0:4] + "-" + dicom_DOB[4:6] + "-" + dicom_DOB[6:8]:
        st.success("DOB: " + DOB)
    else:
        st.error("DOB: " + DOB)

    ########################################################################################################################
    # check the approval status of various sections in Mosaiq
    st.subheader("Approval Status:")

    # check site setup approval
    if all(i == 5 for i in mosaiq_table.iloc[:]["site_setup_status"]):
        st.success("Site Setup Approved")
    else:
        for i in mosaiq_table.iloc[:]["site_setup_status"]:
            if i != 5:
                st.error("Site Setup " + SITE_CONSTANTS[i])
                break

    # check site approval
    if all(i == 5 for i in mosaiq_table.iloc[:]["site_status"]):
        st.success("RX Approved by " + str(site_initials[0][0]))
    else:
        st.error("RX Approval Pending")
    ########################################################################################################################
    # create a list of all the fields in the DICOM RP file
    index = []
    for j in dicom_table.iloc[:]["field_label"]:
        for i in range(len(mosaiq_table)):
            if mosaiq_table.iloc[i]["field_label"] == j:
                index.append(i)
    # remove any fields in Mosaiq that are not being compared to this particular RP file
    remove = []
    for i in mosaiq_table.iloc[:].index:
        if i not in index:
            remove.append(i)

    mosaiq_table = mosaiq_table.drop(remove)
    mosaiq_table = mosaiq_table.sort_index(axis=1)
    mosaiq_table = mosaiq_table.sort_values(by=["field_label"])

    # compare values between the two systems and create a new dataframe with the results
    results = compare_to_mosaiq(dicom_table, mosaiq_table)
    results = results.transpose()

    # create a dropdown menu of prescriptions in mosaiq to choose from
    rx_selection = st.radio("Select RX: ", mosaiq_table.site.unique())
    rx_fields = mosaiq_table[mosaiq_table["site"] == rx_selection]["field_name"].values

    # create a drop down menu to select fields to compare, only fields within selected rx appear as choices
    field_selection = st.radio("Select field to compare:", rx_fields)
    st.subheader("Comparison")

    if len(field_selection) != 0:
        dicom_field = str(field_selection) + "_DICOM"
        mosaiq_field = str(field_selection) + "_MOSAIQ"
        st.write("**RX**: ", results[field_selection + "_DICOM"]["rx"])

        try:
            field_approval_id = mosaiq_table[
                mosaiq_table["field_name"] == field_selection
            ]["field_approval"]
            with connect.connect(server) as cursor:
                field_approval_initials = get_staff_initials(
                    cursor, str(int(field_approval_id.iloc[0]))
                )
            st.write("**Field Approved by: **", field_approval_initials[0][0])
        except (TypeError, ValueError, AttributeError):
            st.write("This field is not approved.")

        display_results = results[[dicom_field, mosaiq_field]]
        display_results = display_results.drop(
            ["dob", "first_name", "last_name", "mrn"], axis=0
        )
        display_results = display_results.style.apply(color_results, axis=1)
        st.dataframe(display_results, height=1000)

    fx_pattern = mosaiq_table[mosaiq_table["field_name"] == field_selection][
        "fraction_pattern"
    ]
    st.write("**FX Pattern**: ", fx_pattern.iloc[0])

    comments = mosaiq_table[mosaiq_table["field_name"] == field_selection]["notes"]
    st.write("**Comments**: ", comments.iloc[0])

    show_dicom = st.checkbox("View complete DICOM table.")
    if show_dicom:
        st.subheader("DICOM Table")
        st.dataframe(dicom_table, height=1000)

    show_mosaiq = st.checkbox("View complete Mosaiq table.")
    if show_mosaiq:
        st.subheader("Mosaiq Table")
        st.dataframe(mosaiq_table, height=1000)

    # if 'rs' in files and 'rd' in files:
    #     plot_dvh(files['rs'], files['rd'])
