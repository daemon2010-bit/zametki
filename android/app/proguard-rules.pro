# Keep Kotlinx Serialization models and serializers
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.zametki.app.model.**$$serializer { *; }
-keepclassmembers class com.zametki.app.model.** {
    *** Companion;
}
-keepclasseswithmembers class com.zametki.app.model.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Keep ZXing capture activity
-keep class com.zametki.app.PortraitCaptureActivity { *; }
-keep class com.journeyapps.barcodescanner.** { *; }
