document.addEventListener("DOMContentLoaded", function () {
    const calendarEl = document.getElementById("calendar");

    function getCSRFToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]').value;
    }

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: "timeGridWeek",
        locale: "pl",
        firstDay: 1,
        slotMinTime: "07:00:00",
        slotMaxTime: "22:00:00",
        height: "auto",
        headerToolbar: {
            left: "prev,next today",
            center: "title",
            right: "dayGridMonth,timeGridWeek,timeGridDay"
        },
        selectable: true,
        editable: false,

        events: "/calendar/events/", // endpoint zwracający wszystkie wizyty

        eventDidMount: function(info){
            const status = info.event.extendedProps.status;
            if(status === "potwierdzona") info.el.style.backgroundColor = "#3498db";
            if(status === "odbyta") info.el.style.backgroundColor = "#2ecc71";
            if(status === "anulowana") info.el.style.backgroundColor = "#e74c3c";
            if(info.event.title === "Zajęty") info.el.style.backgroundColor = "#808080";
        },

        // kliknięcie w slot = rezerwacja
        select: function(info) {
            const startDate = new Date(info.start);
            const nowDate = new Date();

            if(startDate < nowDate) { alert("Nie można umawiać wizyt w przeszłości"); return; }
            if(startDate.getDay() === 0 || startDate.getDay() === 6) { alert("Nie można umawiać wizyt w weekendy"); return; }

            if(!confirm("Czy chcesz zarezerwować ten termin?")) return;

            fetch("/wizyta/umow/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify({
                    start: info.startStr,
                    end: info.endStr
                })
            })
            .then(res => res.json())
            .then(data => {
                if(data.status === "ok"){
                    alert("Wizyta zapisana ✅");
                    calendar.refetchEvents();
                } else {
                    alert(data.error || "Błąd przy zapisie wizyty ❌");
                }
            });
        },

        eventClick: function(info) {
            if(info.event.title === "Zajęty") {
                alert("Termin zajęty przez innego klienta");
                return;
            }
            alert("Klient: " + info.event.title + "\n" +
                  "Od: " + info.event.start.toLocaleString() + "\n" +
                  "Do: " + info.event.end.toLocaleString() + "\n" +
                  "Status: " + info.event.extendedProps.status);
        }

    });

    calendar.render();
});